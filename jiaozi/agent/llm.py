"""OpenAI 兼容 LLM 客户端（纯 urllib，无 SDK 依赖）。

支持：流式输出、增量 tool_calls 拼装、模型列表、连通性测试。
适配 Ollama / llama.cpp server / vLLM / LM Studio / DeepSeek / 任何 OpenAI 兼容网关。
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .. import config

_LOCAL_HOSTS = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|::1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|"
    r"192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|.*\.local)$", re.I)


class LLMError(Exception):
    def __init__(self, msg: str, status: int = 0, raw: str = ""):
        super().__init__(msg)
        self.status = status
        self.raw = raw


class LLMClient:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or config.load()
        self.cfg = cfg["llm"]
        self.base = (self.cfg.get("base_url") or "").rstrip("/")

    # ---------- 基础 ----------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self.cfg.get("api_key") or ""
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def _url(self, path: str) -> str:
        base = self.base
        if not base.endswith("/v1") and "/v1" not in base:
            base = base + "/v1"
        return f"{base}{path}"

    def _opener(self):
        """本机 / 局域网模型直连，绕开系统代理（否则 localhost 请求会被代理打回 502）。"""
        if getattr(self, "_op", None) is None:
            host = urllib.parse.urlparse(self.base).hostname or ""
            if _LOCAL_HOSTS.match(host):
                self._op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            else:
                self._op = urllib.request.build_opener()
        return self._op

    def _request(self, path: str, payload: dict | None = None, method: str = "POST",
                 stream: bool = False, timeout: int | None = None):
        url = self._url(path)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        to = timeout or int(self.cfg.get("timeout") or 180)
        try:
            return self._opener().open(req, timeout=to)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:2000]
            except Exception:
                pass
            raise LLMError(f"模型服务返回 {e.code}: {body or e.reason}", e.code, body) from e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            raise LLMError(f"连不上模型服务 {url}：{e}") from e

    # ---------- 模型列表 ----------
    def models(self) -> list[str]:
        try:
            with self._request("/models", method="GET", timeout=12) as r:
                obj = json.loads(r.read().decode("utf-8", "replace"))
            items = obj.get("data") or obj.get("models") or []
            out = []
            for it in items:
                if isinstance(it, str):
                    out.append(it)
                elif isinstance(it, dict):
                    n = it.get("id") or it.get("name") or it.get("model")
                    if n:
                        out.append(str(n))
            return sorted(set(out))
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"读取模型列表失败: {e}") from e

    def ping(self) -> dict:
        try:
            ms = self.models()
            return {"ok": True, "models": ms, "base_url": self.base}
        except LLMError as e:
            return {"ok": False, "error": str(e), "base_url": self.base}

    # ---------- 对话 ----------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             on_delta: Callable[[str], None] | None = None,
             stream: bool | None = None) -> dict:
        stream = self.cfg.get("stream", True) if stream is None else stream
        payload: dict = {
            "model": self.cfg.get("model"),
            "messages": messages,
            "temperature": float(self.cfg.get("temperature", 0.3)),
            "max_tokens": int(self.cfg.get("max_tokens", 1024)),
            "stream": bool(stream),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if not stream:
            return self._chat_once(payload)
        try:
            return self._chat_stream(payload, on_delta)
        except LLMError as e:
            # 某些服务端声明支持 stream 但实现有问题
            if e.status in (400, 422, 500) and "stream" in (e.raw or "").lower():
                payload["stream"] = False
                return self._chat_once(payload)
            raise

    def _chat_once(self, payload: dict) -> dict:
        with self._request("/chat/completions", payload) as r:
            obj = json.loads(r.read().decode("utf-8", "replace"))
        msg = (obj.get("choices") or [{}])[0].get("message") or {}
        return {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": self._normalize_tool_calls(msg.get("tool_calls") or []),
            "usage": obj.get("usage") or {},
        }

    def _chat_stream(self, payload: dict, on_delta: Callable[[str], None] | None) -> dict:
        content_parts: list[str] = []
        calls: dict[int, dict] = {}
        usage: dict = {}
        with self._request("/chat/completions", payload, stream=True) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices") or []:
                    delta = ch.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        content_parts.append(piece)
                        if on_delta:
                            on_delta(piece)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = (slot["name"] + fn["name"]) if slot["name"] and not slot["name"].endswith(fn["name"]) else fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if ch.get("finish_reason"):
                        pass
        tool_calls = []
        for idx in sorted(calls):
            c = calls[idx]
            if not c["name"]:
                continue
            tool_calls.append({
                "id": c["id"] or f"call_{idx}",
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
            })
        return {"role": "assistant", "content": "".join(content_parts),
                "tool_calls": tool_calls, "usage": usage}

    @staticmethod
    def _normalize_tool_calls(raw: list) -> list[dict]:
        out = []
        for i, tc in enumerate(raw or []):
            fn = (tc or {}).get("function") or {}
            if not fn.get("name"):
                continue
            args = fn.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args or {}, ensure_ascii=False)
            out.append({"id": tc.get("id") or f"call_{i}", "type": "function",
                        "function": {"name": fn["name"], "arguments": args}})
        return out
