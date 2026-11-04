"""Agent 主循环。

两种模式：
- native=True  用 OpenAI 的 function calling（Qwen2.5-7B/DeepSeek 等较新模型）
- native=False 用提示协议解析 ```json {"tool":...}```（0.5B~3B 小模型在开发板上更稳）

两种模式共用同一套工具、同一套审批、同一套事件流。
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import uuid

from .. import config
from ..eventbus import BUS
from . import tools as T
from .llm import LLMClient, LLMError
from .prompts import system_prompt, tools_text

TOOL_BLOCK = re.compile(r"```(?:json|JSON)?\s*(\{[\s\S]*?\})\s*```")
BARE_TOOL = re.compile(r"(\{\s*\"tool\"\s*:[\s\S]*\})\s*$")


def _parse_tool_text(text: str) -> dict | None:
    """从模型自由文本里抠出一次工具调用。"""
    if not text:
        return None
    for m in TOOL_BLOCK.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("tool"):
            return obj
    m = BARE_TOOL.search(text.strip())
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj.get("tool"):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _loads_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        # 小模型常写出单引号或不闭合的 JSON，尽量救一下
        try:
            fixed = raw.replace("'", '"')
            obj = json.loads(fixed)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}


class AgentSession:
    """一个会话 = 一段上下文 + 待审批队列。"""

    def __init__(self, sid: str = "main"):
        self.sid = sid
        self.messages: list[dict] = []
        self.approved: set[str] = set()
        self.pending: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._path = config.HISTORY_DIR / f"{sid}.json"
        self.busy = False
        self.load()

    # ---------------- 持久化 ----------------
    def load(self) -> None:
        try:
            if self._path.exists():
                obj = json.loads(self._path.read_text("utf-8"))
                self.messages = obj.get("messages") or []
        except Exception:
            self.messages = []

    def save(self) -> None:
        try:
            self._path.write_text(json.dumps(
                {"messages": self.messages[-80:], "updated": time.time()},
                ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass

    def reset(self) -> None:
        with self._lock:
            self.messages = []
            self.approved.clear()
        self.save()

    def history(self) -> list[dict]:
        out = []
        for m in self.messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                content = m.get("content") or ""
                if content.strip():
                    out.append({"role": role, "content": content,
                                "ts": m.get("ts")})
        return out

    # ---------------- 审批 ----------------
    def _wait_approval(self, name: str, args: dict, summary: str,
                       emit=None, timeout: int = 300) -> bool:
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        self.pending[aid] = {"event": ev, "ok": False, "name": name}
        payload = {"t": "approval", "id": aid, "name": name, "args": args,
                   "summary": summary}
        if emit:
            emit(payload)
        BUS.publish("approval", {"id": aid, "tool": name, "args": args,
                                 "summary": summary, "sid": self.sid})
        got = ev.wait(timeout)
        slot = self.pending.pop(aid, None)
        if not got or not slot:
            BUS.publish("approval_result", {"id": aid, "ok": False, "timeout": True})
            if emit:
                emit({"t": "approval_result", "id": aid, "ok": False})
            return False
        BUS.publish("approval_result", {"id": aid, "ok": slot["ok"]})
        if emit:
            emit({"t": "approval_result", "id": aid, "ok": slot["ok"]})
        return bool(slot["ok"])

    def approve(self, aid: str, ok: bool) -> bool:
        slot = self.pending.get(aid)
        if not slot:
            return False
        slot["ok"] = ok
        slot["event"].set()
        return True

    # ---------------- 主循环 ----------------
    def run(self, text: str, cid: str = ""):
        """生成器：产出给前端的事件流。"""
        q: queue.Queue = queue.Queue()

        def emit(ev: dict) -> None:
            q.put(ev)

        def worker() -> None:
            try:
                self._loop(text, emit, cid)
            except Exception as e:  # noqa: BLE001
                emit({"t": "error", "d": f"{type(e).__name__}: {e}"})
            finally:
                q.put(None)

        self.busy = True
        threading.Thread(target=worker, daemon=True).start()
        try:
            while True:
                ev = q.get()
                if ev is None:
                    break
                if ev.get("t") not in ("delta",):
                    BUS.publish("agent_event", ev)
                yield ev
        finally:
            self.busy = False
            self.save()

    def _build_messages(self, native: bool) -> list[dict]:
        cfg = config.load()
        sys_msg = {"role": "system",
                   "content": system_prompt(cfg["llm"].get("model", ""),
                                            tools_text(), native)}
        body = list(self.messages)
        # 控制上下文长度，小模型的窗口很宝贵
        keep = 14 if not native else 24
        if len(body) > keep:
            body = body[-keep:]
            while body and body[0].get("role") == "tool":
                body.pop(0)
        # 单条工具结果过长会挤爆上下文
        trimmed = []
        for m in body:
            if m.get("role") == "tool" and len(m.get("content") or "") > 3000:
                m = dict(m)
                m["content"] = m["content"][:3000] + "\n...[截断]"
            trimmed.append(m)
        return [sys_msg] + trimmed

    def _loop(self, text: str, emit, cid: str) -> None:
        cfg = config.load()
        native = bool(cfg["llm"].get("native_tools", True))
        max_steps = int(cfg["agent"].get("max_steps", 12))
        policy = cfg["agent"].get("approval", "auto")
        client = LLMClient(cfg)

        self.messages.append({"role": "user", "content": text, "ts": time.time()})
        emit({"t": "start", "sid": self.sid, "native": native})

        final_text = ""
        used_tools: list[dict] = []

        for step in range(1, max_steps + 1):
            emit({"t": "step", "i": step, "max": max_steps})
            msgs = self._build_messages(native)
            spec = T.TOOL_SPECS if native else None
            try:
                resp = self._chat(client, msgs, spec, emit, native)
            except LLMError as e:
                # 模型不支持 function calling → 自动降级重试一次
                if native and e.status in (400, 422, 404, 500):
                    emit({"t": "warn",
                          "d": f"该模型不接受函数调用，已切换到提示协议。({e})"})
                    native = False
                    try:
                        resp = self._chat(client, self._build_messages(False), None, emit, False)
                    except LLMError as e2:
                        emit({"t": "error", "d": str(e2)})
                        return
                else:
                    emit({"t": "error", "d": str(e)})
                    return

            content = (resp.get("content") or "").strip()
            calls = resp.get("tool_calls") or []
            parsed_from_text = None
            if not native and not calls:
                parsed_from_text = _parse_tool_text(content)
                if parsed_from_text:
                    calls = [{"id": f"call_{uuid.uuid4().hex[:6]}", "type": "function",
                              "function": {"name": parsed_from_text.get("tool"),
                                           "arguments": json.dumps(
                                               parsed_from_text.get("args") or {},
                                               ensure_ascii=False)}}]

            if not calls:
                final_text = content
                # 提示协议下可能把思考文字也带出来了，去掉工具块再展示
                clean = TOOL_BLOCK.sub("", content).strip() if not native else content
                if clean and clean != content:
                    emit({"t": "final_replace", "d": clean})
                self.messages.append({"role": "assistant", "content": content,
                                      "ts": time.time()})
                break

            # ---- 记录 assistant 消息（原生协议需要带 tool_calls）----
            if native:
                self.messages.append({"role": "assistant", "content": content,
                                      "tool_calls": calls, "ts": time.time()})
            else:
                self.messages.append({"role": "assistant", "content": content,
                                      "ts": time.time()})

            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = _loads_args(fn.get("arguments"))
                tc_id = call.get("id") or f"call_{uuid.uuid4().hex[:6]}"
                summary = T.tool_summary(name, args)
                emit({"t": "tool", "status": "running", "name": name,
                      "args": args, "summary": summary, "id": tc_id})

                if name not in T.TOOL_NAMES and name not in T._EXTRA_IMPL:
                    result = f"错误：没有名为 {name} 的工具。可用工具：{', '.join(T.TOOL_NAMES)}"
                else:
                    need = (policy == "always") or (
                        policy == "auto" and name in T.DANGEROUS)
                    if need and name not in self.approved:
                        ok = self._wait_approval(name, args, summary, emit)
                        if not ok:
                            result = "用户拒绝了该操作。请换一种方式，或询问用户要怎么做。"
                            emit({"t": "tool", "status": "denied", "name": name,
                                  "args": args, "summary": summary, "id": tc_id})
                            self._append_tool_result(native, tc_id, name, result)
                            continue
                        self.approved.add(name)
                    result = T.dispatch(name, args)
                    emit({"t": "tool", "status": "ok", "name": name, "args": args,
                          "summary": summary, "id": tc_id,
                          "result": result[:1200]})
                used_tools.append({"name": name, "args": args, "summary": summary})
                self._append_tool_result(native, tc_id, name, result)

        else:
            emit({"t": "warn", "d": f"已达到最大步数 {max_steps}，先停下汇报。"})

        emit({"t": "done", "content": final_text, "tools": used_tools,
              "sid": self.sid})

    def _append_tool_result(self, native: bool, tc_id: str, name: str, result: str) -> None:
        if native:
            self.messages.append({"role": "tool", "tool_call_id": tc_id,
                                  "name": name, "content": result})
        else:
            self.messages.append({"role": "user",
                                  "content": f"【工具结果 · {name}】\n{result}",
                                  "ts": time.time()})

    def _chat(self, client: LLMClient, msgs: list[dict], spec, emit, native: bool) -> dict:
        """流式对话；边收边发，前端才能看到逐字输出。"""
        parts: list[str] = []

        def on_delta(d: str) -> None:
            parts.append(d)
            emit({"t": "delta", "d": d})

        return client.chat(msgs, tools=spec, on_delta=on_delta)


_SESSIONS: dict[str, AgentSession] = {}
_SLOCK = threading.RLock()


def get_session(sid: str = "main") -> AgentSession:
    with _SLOCK:
        if sid not in _SESSIONS:
            _SESSIONS[sid] = AgentSession(sid)
        return _SESSIONS[sid]
