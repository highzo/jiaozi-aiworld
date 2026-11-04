"""终端会话。

POSIX 用真 PTY（所以 bash / top / 交互式程序都能跑）；
Windows 没有 pty.fork，退化到管道模式（无作业控制、无 Ctrl+C，
启动时会打印一行说明）。回显由 shell 自己做，前端不补字符。
"""
from __future__ import annotations

import codecs
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from typing import Callable

from . import config
from .eventbus import BUS

IS_POSIX = os.name == "posix"

# bash 在无 tty 时的两行固定告警（实测各占一行，见 tests 手工核对）
_PIPE_NOISE = re.compile(
    r"^bash: cannot set terminal process group.*\n"
    r"|^bash: no job control in this shell.*\n",
    re.M,
)


class OutputBuffer:
    """会话输出环形缓冲：SSE 断线重连后可以补齐，不丢历史。"""

    def __init__(self, limit: int = 96_000):
        self.parts: list[str] = []
        self.size = 0
        self.limit = limit

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.size += len(text)
        while self.size > self.limit and len(self.parts) > 1:
            self.size -= len(self.parts.pop(0))

    def text(self) -> str:
        return "".join(self.parts)


class BaseSession:
    def __init__(self, sid: str, shell: str, cols: int, rows: int,
                 on_output: Callable[[str], None], title: str = "终端"):
        self.id = sid
        self.shell = shell
        self.cols = cols
        self.rows = rows
        self.title = title
        self.on_output = on_output
        self.alive = True
        self.tty = IS_POSIX
        self.created = time.time()
        self.buffer = OutputBuffer()

    def write(self, data: str) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    def kill(self) -> None: ...


class PtySession(BaseSession):
    def __init__(self, sid: str, shell: str, cols: int, rows: int,
                 on_output: Callable[[str], None], title: str = "终端"):
        super().__init__(sid, shell, cols, rows, on_output, title)
        import fcntl
        import pty
        import struct
        import termios

        self._fcntl = fcntl
        self._termios = termios
        pid, fd = pty.fork()
        if pid == 0:  # 子进程
            try:
                os.environ["TERM"] = "xterm-256color"
                os.environ["COLORTERM"] = "truecolor"
                os.environ.setdefault("LANG", "C.UTF-8")
                os.chdir(str(config.sandbox_roots()[0]))
                argv = [shell, "-i"] if os.path.basename(shell) in (
                    "bash", "zsh", "sh", "fish", "dash") else [shell]
                os.execvp(shell, argv)
            except Exception:
                os._exit(127)
        self.pid = pid
        self.fd = fd
        self._set_size(cols, rows)
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    def _set_size(self, cols: int, rows: int) -> None:
        import struct
        try:
            self._fcntl.ioctl(self.fd, self._termios.TIOCSWINSZ,
                              struct.pack("HHHH", max(rows, 2), max(cols, 20), 0, 0))
        except Exception:
            pass

    def _reader(self) -> None:
        while self.alive:
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                break
            if not data:
                break
            try:
                text = data.decode("utf-8", "replace")
            except Exception:
                text = data.decode("latin-1", "replace")
            self.on_output(text)
        self.alive = False
        try:
            os.close(self.fd)
        except OSError:
            pass

    def write(self, data: str) -> None:
        if not self.alive:
            return
        try:
            os.write(self.fd, data.encode("utf-8", "replace"))
        except OSError:
            self.alive = False

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self._set_size(cols, rows)

    def kill(self) -> None:
        self.alive = False
        try:
            os.kill(self.pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            pass


class PipeSession(BaseSession):
    """Windows / 无 PTY 环境：管道 + 本地回显。"""

    def __init__(self, sid: str, shell: str, cols: int, rows: int,
                 on_output: Callable[[str], None], title: str = "终端"):
        super().__init__(sid, shell, cols, rows, on_output, title)
        self.tty = False
        self._noticed = False
        args = [shell]
        if os.path.basename(shell).startswith("bash"):
            args = [shell, "--noprofile", "--norc", "-i"]
        env = dict(os.environ)
        env["TERM"] = "dumb"
        env["PYTHONIOENCODING"] = "utf-8"
        kwargs: dict = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0, env=env,
                            cwd=str(config.sandbox_roots()[0]))
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(args, **kwargs)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc.stdout is not None
        # 关键：不能攒到换行才发。shell 的提示符（如 "bash-5.3$ "）本身不带换行，
        # 攒就会导致刚打开终端一片空白，用户以为没起来。
        # bufsize=0 时 read() 有多少返回多少，拿到就发即可。
        # 用增量解码器，避免一个 UTF-8 汉字被切在两次 read 之间变成乱码。
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while self.alive:
            try:
                chunk = self.proc.stdout.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            try:
                text = dec.decode(chunk)
            except Exception:
                continue
            if text:
                self._emit(text)
        try:
            tail = dec.decode(b"", True)
            if tail:
                self._emit(tail)
        except Exception:
            pass
        self.alive = False

    def _emit(self, text: str) -> None:
        """过滤 bash 在没有 tty 时的两行告警，换成一句人话。

        这两行（`cannot set terminal process group` / `no job control`）
        是无 PTY 环境的必然产物，不是故障，但英文堆在终端第一屏会让人
        以为系统坏了。Linux / 安卓 走的是真 PTY，不会走到这里。
        """
        text = _PIPE_NOISE.sub("", text)
        if not self._noticed:
            self._noticed = True
            text = ("\x1b[33m[兼容模式] 本平台没有 PTY：Ctrl+C 与后台作业不可用。"
                    "Linux / 安卓上是完整终端。\x1b[0m\r\n") + text
        if text:
            self.on_output(text)

    def write(self, data: str) -> None:
        if not self.alive or self.proc.stdin is None:
            return
        # 管道模式没有行编辑，回车需要转成换行
        payload = data.replace("\r", "\n")
        try:
            self.proc.stdin.write(payload.encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.alive = False

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows

    def kill(self) -> None:
        self.alive = False
        try:
            self.proc.kill()
        except Exception:
            pass


class ShellManager:
    MAX_SESSIONS = 32

    def __init__(self) -> None:
        self.sessions: dict[str, BaseSession] = {}
        self._lock = threading.RLock()

    def open(self, *, cols: int = 100, rows: int = 30, shell: str | None = None,
             title: str = "终端") -> dict:
        sid = uuid.uuid4().hex[:12]
        sh = shell or config.default_shell()

        buf = OutputBuffer()

        def on_out(text: str) -> None:
            buf.add(text)
            BUS.term(sid, text)

        cls = PtySession if IS_POSIX else PipeSession
        try:
            sess = cls(sid, sh, cols, rows, on_out, title)
        except Exception as e:
            raise RuntimeError(f"无法启动终端 {sh}: {e}") from e
        sess.buffer = buf
        with self._lock:
            self.sessions[sid] = sess
            # 页面异常退出可能留下孤儿会话，按数量上限回收最老的
            if len(self.sessions) > self.MAX_SESSIONS:
                alive = [s for s in self.sessions.values() if s.id != sid]
                if alive:
                    victim = min(alive, key=lambda s: s.created)
                    threading.Thread(target=self.close, args=(victim.id,), daemon=True).start()
        BUS.publish("term_open", {"id": sid, "shell": sh, "tty": sess.tty})
        return {"id": sid, "shell": sh, "tty": sess.tty, "title": title,
                "cols": cols, "rows": rows}

    def get(self, sid: str) -> BaseSession | None:
        return self.sessions.get(sid)

    def write(self, sid: str, data: str) -> bool:
        s = self.get(sid)
        if not s or not s.alive:
            return False
        s.write(data)
        return True

    def resize(self, sid: str, cols: int, rows: int) -> None:
        s = self.get(sid)
        if s:
            s.resize(cols, rows)

    def close(self, sid: str) -> None:
        with self._lock:
            s = self.sessions.pop(sid, None)
        if s:
            s.kill()
            BUS.publish("term_close", {"id": sid})

    def close_all(self) -> None:
        for sid in list(self.sessions):
            self.close(sid)

    # ---- 一次性执行（AI 工具用）----
    def run(self, cmd: str, cwd: str | None = None, timeout: int = 60,
            max_output: int = 8000) -> dict:
        cfg = config.load()
        timeout = max(1, min(int(timeout or cfg["agent"]["shell_timeout"]), 600))
        workdir = None
        try:
            if cwd:
                from . import fsapi
                workdir = str(fsapi.resolve(cwd))
        except Exception:
            workdir = None
        if not workdir:
            workdir = str(config.sandbox_roots()[0])
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=workdir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=timeout,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            out = proc.stdout.decode("utf-8", "replace")
            code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode("utf-8", "replace")
            code = -1
            timed_out = True
        truncated = len(out) > max_output
        if truncated:
            out = out[:max_output] + f"\n...[输出截断，共 {len(out)} 字符]"
        return {"cmd": cmd, "cwd": workdir, "exit_code": code, "output": out,
                "duration": round(time.time() - t0, 3), "timeout": timed_out,
                "truncated": truncated}

    def active(self) -> list[dict]:
        with self._lock:
            return [{"id": s.id, "title": s.title, "shell": s.shell,
                     "alive": s.alive, "tty": s.tty,
                     "cols": s.cols, "rows": s.rows} for s in self.sessions.values()]


SHELLS = ShellManager()
