"""饺子AIWorld HTTP 内核。

只用标准库：http.server + ThreadingHTTPServer + SSE。
没有 pip install，没有 node_modules —— 一块 8G 内存的开发板也能跑起来。
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import re
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, fsapi, sysinfo
from .agent import tools as T
from .agent.llm import LLMClient, LLMError
from .agent.loop import get_session
from .eventbus import BUS, sse_format
from .shell import SHELLS

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json",
}

ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn.__name__))
        return fn
    return deco


class ApiError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code
        self.msg = msg


class Handler(BaseHTTPRequestHandler):
    server_version = f"JiaoziAIWorld/{config.VERSION}"
    protocol_version = "HTTP/1.1"
    _head_only = False

    # ---------------- 基础响应 ----------------
    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("JIAOZI_QUIET"):
            return
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jiaozi-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    def send_json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self._head_only:
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_bytes(self, data: bytes, ctype: str, code: int = 200,
                   extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self._head_only:
            return
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 128 * 1024 * 1024:
            raise ApiError("请求体过大", 413)
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {"value": obj}
        except Exception as e:
            raise ApiError(f"JSON 解析失败: {e}") from e

    # ---------------- SSE（分块传输） ----------------
    def start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

    def sse_write(self, data: bytes) -> None:
        if not data:
            return
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def sse_end(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    # ---------------- 鉴权 ----------------
    def authed(self) -> bool:
        cfg = config.load()
        token = cfg["auth"]["token"]
        if not token:
            return True
        if cfg["server"].get("allow_localhost", True):
            host = (self.client_address or ["", 0])[0]
            if host in ("127.0.0.1", "::1", "localhost"):
                return True
        given = self.headers.get("X-Jiaozi-Token") or ""
        if not given:
            m = re.search(r'(?:^|;\s*)jz_token=([^;]+)', self.headers.get("Cookie") or "")
            if m:
                given = urllib.parse.unquote(m.group(1))
        if not given:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            given = (q.get("token") or [""])[0]
        return given == token

    # ---------------- 分发 ----------------
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self._head_only = False
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        # 部分反代 / 健康检查 / curl -I 会发 HEAD，按 GET 处理但不写响应体
        self._head_only = True
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._head_only = False
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._head_only = False
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            is_api = path.startswith("/api/")
            if is_api and not self.authed():
                self.send_json({"ok": False, "error": "未授权：需要 token"}, 401)
                return
            # 路由表对根路径也生效（/favicon.ico、/manifest.webmanifest）；
            # 否则这些请求会掉进静态目录里变成 404
            for m, rx, fname in ROUTES:
                if m != method:
                    continue
                mt = rx.match(path)
                if mt:
                    getattr(self, fname)(query, *mt.groups())
                    return
            if is_api:
                self.send_json({"ok": False, "error": f"接口不存在 {path}"}, 404)
                return
            if method == "GET":
                self.serve_static(path, query)
            else:
                self.send_json({"ok": False, "error": "not found"}, 404)
        except ApiError as e:
            self.send_json({"ok": False, "error": e.msg}, e.code)
        except fsapi.FSError as e:
            self.send_json({"ok": False, "error": str(e)}, e.code)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            try:
                self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    # ---------------- 静态资源 ----------------
    def serve_static(self, path: str, query: dict) -> None:
        rel = path.lstrip("/") or "index.html"
        rel = posixpath.normpath(rel)
        if rel.startswith("..") or rel.startswith("/"):
            self.send_bytes(b"forbidden", "text/plain", 403)
            return
        fp = (config.DESKTOP_DIR / rel).resolve()
        try:
            if config.DESKTOP_DIR.resolve() not in fp.parents and fp != config.DESKTOP_DIR.resolve():
                self.send_bytes(b"forbidden", "text/plain", 403)
                return
        except Exception:
            self.send_bytes(b"forbidden", "text/plain", 403)
            return
        if fp.is_dir():
            fp = fp / "index.html"
        if not fp.exists():
            self.send_bytes(b"404 not found", "text/plain; charset=utf-8", 404)
            return
        data = fp.read_bytes()
        ctype = MIME.get(fp.suffix.lower()) or mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        extra = {}
        # 带 token 首次访问 → 写 cookie，之后 EventSource / fetch 才能带上。
        # Max-Age 让 cookie 持久化：否则手机「添加到主屏幕」后关掉再打开，
        # 会话级 cookie 没了，整个界面会 401。
        if rel == "index.html":
            t = (query.get("token") or [""])[0]
            cfg = config.load()
            if t and t == cfg["auth"]["token"]:
                extra["Set-Cookie"] = (
                    f"jz_token={urllib.parse.quote(t)}; Path=/; Max-Age=2592000; SameSite=Lax"
                )
        self.send_bytes(data, ctype, 200, extra)

    # ================================================================ 系统
    @route("GET", r"/api/health")
    def api_health(self, q):
        self.send_json({"ok": True, "app": config.APP_NAME, "version": config.VERSION,
                        "time": time.time(), "clients": BUS.count(),
                        "platform": os.name, "pid": os.getpid()})

    @route("GET", r"/api/ping")
    def api_ping(self, q):
        self.send_json({"ok": True, "pong": time.time()})

    @route("GET", r"/api/sys/info")
    def api_sysinfo(self, q):
        data = sysinfo.info()
        data["clients"] = BUS.count()
        data["sessions"] = SHELLS.active()
        self.send_json({"ok": True, "data": data})

    @route("GET", r"/api/sys/proc")
    def api_proc(self, q):
        limit = int((q.get("limit") or ["40"])[0])
        self.send_json({"ok": True, "data": sysinfo.processes(limit)})

    @route("POST", r"/api/sys/kill")
    def api_kill(self, q):
        body = self.read_json()
        self.send_json({"ok": True, "data": sysinfo.kill(int(body["pid"]),
                                                         bool(body.get("force", True)))})

    # ================================================================ 配置
    @route("GET", r"/api/config")
    def api_config_get(self, q):
        self.send_json({"ok": True, "data": config.public_view()})

    @route("POST", r"/api/config")
    def api_config_set(self, q):
        body = self.read_json()
        cur = config.load()
        clean: dict = {}
        allowed = {"server", "fs", "llm", "agent", "ui", "shell", "device"}
        for k, v in body.items():
            if k in allowed and isinstance(v, dict):
                clean[k] = v
        # 掩码的 api_key 不覆盖真实值
        if clean.get("llm", {}).get("api_key", "").startswith("****"):
            clean["llm"].pop("api_key", None)
        if clean.get("ui", {}).get("accent") and not re.match(r"^#[0-9a-fA-F]{6}$", clean["ui"]["accent"]):
            clean["ui"].pop("accent", None)
        cfg = config.save(clean)
        BUS.publish("config", {"changed": list(clean.keys())})
        self.send_json({"ok": True, "data": config.public_view(cfg)})

    # ================================================================ 文件
    @route("GET", r"/api/fs/list")
    def api_fs_list(self, q):
        p = (q.get("path") or [""])[0] or None
        self.send_json({"ok": True, "data": fsapi.list_dir(p)})

    @route("GET", r"/api/fs/read")
    def api_fs_read(self, q):
        p = (q.get("path") or [""])[0]
        if not p:
            raise ApiError("缺少 path")
        self.send_json({"ok": True, "data": fsapi.read_text(p)})

    @route("GET", r"/api/fs/stat")
    def api_fs_stat(self, q):
        p = (q.get("path") or [""])[0]
        self.send_json({"ok": True, "data": fsapi.stat_entry(fsapi.resolve(p, must_exist=True))})

    @route("GET", r"/api/fs/raw")
    def api_fs_raw(self, q):
        p = (q.get("path") or [""])[0]
        data, ctype = fsapi.read_bytes(p)
        name = os.path.basename(p)
        disp = "inline" if ctype.startswith(("image/", "text/", "application/pdf")) else "attachment"
        self.send_bytes(data, ctype, 200,
                        {"Content-Disposition": f'{disp}; filename="{urllib.parse.quote(name)}"'})

    @route("POST", r"/api/fs/write")
    def api_fs_write(self, q):
        b = self.read_json()
        r = fsapi.write_text(b["path"], b.get("content", ""))
        BUS.publish("fs_change", {"path": r["path"], "action": "write"})
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/fs/mkdir")
    def api_fs_mkdir(self, q):
        b = self.read_json()
        r = fsapi.mkdir(b["path"])
        BUS.publish("fs_change", {"path": r["path"], "action": "mkdir"})
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/fs/rename")
    def api_fs_rename(self, q):
        b = self.read_json()
        r = fsapi.move(b["path"], b["to"])
        BUS.publish("fs_change", {"path": r["path"], "action": "rename"})
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/fs/copy")
    def api_fs_copy(self, q):
        b = self.read_json()
        r = fsapi.copy(b["path"], b["to"])
        BUS.publish("fs_change", {"path": r["path"], "action": "copy"})
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/fs/delete")
    def api_fs_delete(self, q):
        b = self.read_json()
        r = fsapi.delete(b["path"], bool(b.get("hard")))
        BUS.publish("fs_change", {"path": b["path"], "action": "delete"})
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/fs/upload")
    def api_fs_upload(self, q):
        b = self.read_json()
        r = fsapi.save_upload(b["dir"], b["name"], b["data"])
        BUS.publish("fs_change", {"path": r["path"], "action": "upload"})
        self.send_json({"ok": True, "data": r})

    @route("GET", r"/api/fs/search")
    def api_fs_search(self, q):
        query = (q.get("q") or [""])[0]
        root = (q.get("path") or [""])[0] or None
        hits = fsapi.search(root, query, int((q.get("limit") or ["200"])[0]))
        self.send_json({"ok": True, "data": hits})

    @route("GET", r"/api/fs/roots")
    def api_fs_roots(self, q):
        self.send_json({"ok": True, "data": fsapi.roots_view()})

    # ================================================================ 终端
    @route("POST", r"/api/term/open")
    def api_term_open(self, q):
        b = self.read_json()
        r = SHELLS.open(cols=int(b.get("cols") or 100),
                        rows=int(b.get("rows") or 30),
                        shell=b.get("shell") or None,
                        title=b.get("title") or "终端")
        self.send_json({"ok": True, "data": r})

    @route("POST", r"/api/term/input")
    def api_term_input(self, q):
        b = self.read_json()
        ok = SHELLS.write(b["id"], b.get("data", ""))
        self.send_json({"ok": ok})

    @route("POST", r"/api/term/resize")
    def api_term_resize(self, q):
        b = self.read_json()
        SHELLS.resize(b["id"], int(b["cols"]), int(b["rows"]))
        self.send_json({"ok": True})

    @route("POST", r"/api/term/close")
    def api_term_close(self, q):
        b = self.read_json()
        SHELLS.close(b["id"])
        self.send_json({"ok": True})

    @route("GET", r"/api/term/list")
    def api_term_list(self, q):
        self.send_json({"ok": True, "data": SHELLS.active()})

    @route("GET", r"/api/term/buffer")
    def api_term_buffer(self, q):
        sid = (q.get("id") or [""])[0]
        s = SHELLS.get(sid)
        if not s:
            raise ApiError("会话不存在或已结束", 404)
        self.send_json({"ok": True, "data": {"id": sid, "text": s.buffer.text(),
                                             "alive": s.alive, "tty": s.tty}})

    # ================================================================ 事件流
    @route("GET", r"/api/events")
    def api_events(self, q):
        cid = uuid.uuid4().hex[:10]
        sub = BUS.subscribe(cid)
        # ?ms=1500 让事件流在指定毫秒后自行关闭（调试/截图/一次性抓取用）
        bound_ms = 0
        try:
            bound_ms = int((q.get("ms") or ["0"])[0])
        except ValueError:
            bound_ms = 0
        deadline = time.time() + bound_ms / 1000.0 if bound_ms > 0 else 0
        self.start_sse()
        hello = {"t": "hello", "cid": cid, "app": config.APP_NAME,
                 "version": config.VERSION, "ts": time.time()}
        try:
            self.sse_write(sse_format(hello))
            last = time.time()
            while True:
                if deadline and time.time() >= deadline:
                    break
                try:
                    ev = sub.q.get(timeout=5.0 if not deadline else 0.25)
                except Exception:
                    if time.time() - last > 15:
                        self.sse_write(b": keepalive\n\n")
                        last = time.time()
                    continue
                if ev.get("__close__"):
                    break
                self.sse_write(sse_format(ev))
                last = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            BUS.unsubscribe(cid)
            self.sse_end()

    # ================================================================ AI
    @route("GET", r"/api/agent/history")
    def api_agent_history(self, q):
        sid = (q.get("sid") or ["main"])[0]
        s = get_session(sid)
        self.send_json({"ok": True, "data": {"messages": s.history(),
                                             "busy": s.busy}})

    @route("POST", r"/api/agent/reset")
    def api_agent_reset(self, q):
        b = self.read_json()
        get_session(b.get("sid") or "main").reset()
        self.send_json({"ok": True})

    @route("POST", r"/api/agent/approve")
    def api_agent_approve(self, q):
        b = self.read_json()
        s = get_session(b.get("sid") or "main")
        ok = s.approve(b["id"], bool(b.get("ok")))
        self.send_json({"ok": ok})

    @route("POST", r"/api/agent/chat")
    def api_agent_chat(self, q):
        b = self.read_json()
        text = (b.get("text") or "").strip()
        if not text:
            raise ApiError("消息为空")
        sid = b.get("sid") or "main"
        sess = get_session(sid)
        if sess.busy:
            raise ApiError("上一轮还在进行中，请稍等", 409)
        self.start_sse()
        try:
            for ev in sess.run(text, cid=sid):
                self.sse_write(sse_format(ev))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            try:
                self.sse_write(sse_format({"t": "eof"}))
            except Exception:
                pass
            self.sse_end()

    @route("GET", r"/api/llm/models")
    def api_llm_models(self, q):
        try:
            self.send_json({"ok": True, "data": LLMClient().models()})
        except LLMError as e:
            self.send_json({"ok": False, "error": str(e)}, 502)

    @route("POST", r"/api/llm/test")
    def api_llm_test(self, q):
        b = self.read_json()
        cfg = config.load()
        probe = json.loads(json.dumps(cfg))
        for k in ("base_url", "model", "api_key"):
            if b.get(k):
                probe["llm"][k] = b[k]
        r = LLMClient(probe).ping()
        if r.get("ok"):
            try:
                rep = LLMClient(probe).chat(
                    [{"role": "user", "content": "只回复两个字：正常"}],
                    stream=False)
                r["reply"] = (rep.get("content") or "").strip()[:60]
            except LLMError as e:
                r["reply"] = f"(推理测试失败: {e})"
        self.send_json({"ok": bool(r.get("ok")), "data": r})

    @route("GET", r"/api/tools")
    def api_tools(self, q):
        self.send_json({"ok": True, "data": T.TOOL_SPECS})

    # ================================================================ 设备 / 机器人
    @route("GET", r"/api/device/health")
    def api_dev_health(self, q):
        cfg = config.load()
        llm = LLMClient(cfg)
        self.send_json({"ok": True, "data": {
            "brain": "online", "model": cfg["llm"]["model"],
            "llm_endpoint": cfg["llm"]["base_url"],
            "tools": len(T.TOOL_NAMES), "platform": sysinfo.info()["os"],
        }})

    @route("POST", r"/api/device/task")
    def api_dev_task(self, q):
        """给机器人调用：发一句话，拿最终结果。同步阻塞版。"""
        cfg = config.load()
        if not cfg["device"].get("enabled", True):
            raise ApiError("设备接口已关闭", 403)
        b = self.read_json()
        prompt = (b.get("prompt") or b.get("text") or "").strip()
        if not prompt:
            raise ApiError("prompt 为空")
        sid = f"dev-{b.get('device') or 'anon'}"
        sess = get_session(sid)
        if sess.busy:
            raise ApiError("设备正忙", 409)
        t0 = time.time()
        final, steps, err = "", 0, ""
        for ev in sess.run(prompt, cid=sid):
            t = ev.get("t")
            if t == "step":
                steps = ev.get("i", steps)
            elif t == "done":
                final = ev.get("content") or ""
            elif t == "error":
                err = ev.get("d") or ""
        self.send_json({"ok": not err, "error": err or None,
                        "result": final, "steps": steps,
                        "elapsed": round(time.time() - t0, 2)})

    # ================================================================ 杂项
    @route("GET", r"/api/desktop/state")
    def api_desktop_state(self, q):
        cfg = config.load()
        self.send_json({"ok": True, "data": {
            "ui": cfg["ui"], "roots": fsapi.roots_view(),
            "home": str(config.sandbox_roots(cfg)[0]),
            "host": socket.gethostname(),
        }})

    @route("POST", r"/api/desktop/event")
    def api_desktop_event(self, q):
        b = self.read_json()
        BUS.publish("ui", b)
        self.send_json({"ok": True})

    @route("GET", r"/favicon.ico")
    def api_favicon(self, q):
        # 图标是 SVG（见 index.html 的 <link rel="icon">），老的 .ico 请求给个空的
        self.send_bytes(b"", "image/x-icon", 204)

    @route("GET", r"/manifest\.webmanifest")
    def api_manifest(self, q):
        """PWA 清单：安卓 Chrome 可以「添加到主屏幕」，之后全屏运行、无地址栏。

        图标用 SVG 即可（Chrome 支持 sizes="any"），省掉一套 PNG 光栅化流程。
        """
        m = {
            "name": config.APP_NAME,
            "short_name": "饺子",
            "description": "人和 AI 共用一个桌面的 Linux 环境",
            # 不带 token：首次用 /?token=xxx 打开过之后 cookie 就有了，
            # 清单是公开资源，不该把凭据写进去
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#eef2f8",
            "theme_color": "#eef2f8",
            "icons": [
                {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
                 "purpose": "any"},
                {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
                 "purpose": "maskable"},
            ],
        }
        self.send_bytes(json.dumps(m, ensure_ascii=False).encode("utf-8"),
                        "application/manifest+json")


class JiaoziServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # 浏览器刷新页面、关闭标签、SSE 断线都会让 socketserver 抛
        # ConnectionResetError / ConnectionAbortedError。这是正常现象，
        # 不是服务器故障；在开发板/安卓上刷屏会撑爆日志，这里静默掉。
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def serve(host: str = "", port: int = 0, open_browser: bool = False) -> None:
    cfg = config.load()
    host = host or cfg["server"]["host"]
    port = port or int(cfg["server"]["port"])
    httpd = JiaoziServer((host, port), Handler)
    httpd.daemon_threads = True
    real_host = host if host not in ("0.0.0.0", "::") else _lan_ip()
    url = f"http://{real_host}:{port}/"
    tok = cfg["auth"]["token"]
    print("=" * 62)
    print(f"  {config.APP_NAME}  v{config.VERSION}")
    print(f"  打开:  {url}")
    if host in ("0.0.0.0", "::"):
        print(f"  手机/平板: http://{_lan_ip()}:{port}/?token={tok}")
    print(f"  数据:  {config.DATA_DIR}")
    print(f"  停止:  Ctrl+C")
    print("=" * 62)
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        SHELLS.close_all()
        httpd.server_close()


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
