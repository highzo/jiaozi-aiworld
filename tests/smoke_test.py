#!/usr/bin/env python3
"""饺子AIWorld 冒烟测试（零依赖）。

它不只测 HTTP 通不通，还内置了一个假的 OpenAI 兼容模型服务，
把 Agent 循环、工具调用、人工审批、终端 I/O 全部真跑一遍。

用法：
    python tests/smoke_test.py                # 默认测 http://127.0.0.1:8787
    JIAOZI_URL=http://127.0.0.1:8790 python tests/smoke_test.py
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ.get("JIAOZI_URL", "http://127.0.0.1:8787").rstrip("/")
U = urllib.parse.urlparse(BASE)
HOST, PORT = U.hostname or "127.0.0.1", U.port or 8787
MOCK_PORT = int(os.environ.get("MOCK_PORT", "8799"))
# 假模型服务监听地址。跨机器/跨 WSL 测试时设为 0.0.0.0，否则被测服务连不进来。
MOCK_BIND = os.environ.get("MOCK_BIND", "127.0.0.1")
# 告诉被测服务该用哪个地址来连假模型。默认本机回环；
# 测 WSL / 局域网设备时传 http://<这台机器的可达IP>:8799/v1
MOCK_URL = os.environ.get("JIAOZI_MOCK_URL", "http://127.0.0.1:%d/v1" % MOCK_PORT)
# 被测服务的 token。默认从本机 ~/.jiaozi/config.json 读；
# 测远端时本机配置里的 token 对不上，必须显式传。
TOKEN_ENV = os.environ.get("JIAOZI_TOKEN", "")

PASS, FAIL = [], []


def ok(name, cond=True, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  \033[92m✓\033[0m " if cond else "  \033[91m✗\033[0m ") + name +
          (("  — " + str(detail)) if detail and not cond else ""))


def req(method, path, body=None, timeout=30):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    conn.request(method, path, body=payload, headers=headers)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        return r.status, json.loads(raw.decode("utf-8"))
    except Exception:
        return r.status, {"raw": raw[:300].decode("utf-8", "replace")}


#: 1×1 PNG，用来验证「把图存到磁盘」这条链路，不需要真模型
PNG_1X1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
           "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


# ------------------------------------------------------------------ 假模型
class MockLLM(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json({"object": "list", "data": [{"id": "mock-coder", "object": "model"}]})
        else:
            self._json({"error": "not found"}, 404)

    def _chunk(self, text: str):
        data = text.encode()
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages") or []
        stream = body.get("stream")

        # 假文生图端点：验证「生成 → 落盘」链路
        if "/images/generations" in self.path:
            self._json({"created": int(time.time()), "data": [{"b64_json": PNG_1X1, "url": ""}]})
            return

        has_tool_result = any(m.get("role") == "tool" for m in msgs)
        last_user = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                last_user = m.get("content") or ""
                break

        if not has_tool_result:
            if "终端测试" in last_user:
                name = "shell_run"
                args = json.dumps({"cmd": "echo JIAOZI-SHELL-OK"})
            else:
                name = "fs_list"
                args = json.dumps({"path": "~"})
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self._chunk('data: {"choices":[{"delta":{"role":"assistant","content":"我先看一下。"}}]}\n\n')
                half = len(args) // 2
                self._chunk("data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "id": "call_mock", "type": "function",
                     "function": {"name": name, "arguments": args[:half]}}]}}]}) + "\n\n")
                self._chunk("data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"arguments": args[half:]}}]}}]}) + "\n\n")
                self._chunk('data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n')
                self._chunk("data: [DONE]\n\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                self._json({"choices": [{"message": {"role": "assistant", "content": "",
                                                     "tool_calls": [{"id": "call_mock", "type": "function",
                                                                     "function": {"name": name, "arguments": args}}]}}]})
            return

        text = "我看到了结果。任务完成。"
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, len(text), 4):
                piece = text[i:i + 4]
                self._chunk("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n")
                time.sleep(0.01)
            self._chunk('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
            self._chunk("data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            self._json({"choices": [{"message": {"role": "assistant", "content": text}}]})


def start_mock():
    srv = ThreadingHTTPServer((MOCK_BIND, MOCK_PORT), MockLLM)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ SSE 客户端
def stream_post(path, body, on_event, timeout=90):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    payload = json.dumps(body).encode()
    conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    if r.status != 200:
        raw = r.read().decode("utf-8", "replace")
        conn.close()
        raise RuntimeError(f"HTTP {r.status}: {raw[:200]}")
    buf = b""
    while True:
        line = r.readline()
        if not line:
            break
        if not line.startswith(b"data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except Exception:
            continue
        if ev.get("t") == "eof":
            break
        on_event(ev)
    conn.close()


# ------------------------------------------------------------------ 测试项
def test_core():
    print("\n[1] 内核与静态资源")
    st, j = req("GET", "/api/health")
    ok("健康检查", st == 200 and j.get("ok"), j)
    st, j = req("GET", "/api/sys/info")
    ok("系统信息", st == 200 and j["data"]["os"], j.get("error"))
    st, j = req("GET", "/api/desktop/state")
    ok("桌面状态（home/roots）", st == 200 and j["data"].get("home"), j.get("error"))

    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    conn.request("GET", "/")
    r = conn.getresponse()
    html = r.read().decode("utf-8", "replace")
    conn.close()
    ok("首页返回 HTML", r.status == 200 and "饺子AIWorld" in html)
    for asset in ("/css/base.css", "/css/desktop.css", "/css/apps.css",
                  "/js/core.js", "/js/wm.js", "/js/shell.js", "/js/agent.js",
                  "/js/apps/files.js", "/js/apps/terminal.js", "/js/apps/editor.js",
                  "/js/apps/monitor.js", "/js/apps/settings.js", "/js/apps/viewer.js"):
        st, _ = req("GET", asset)
        ok("资源 " + asset, st == 200)


def test_fs():
    print("\n[2] 文件系统（沙箱）")
    st, j = req("GET", "/api/fs/list?path=" + urllib.parse.quote("~"))
    ok("列目录", st == 200 and "items" in j["data"], j.get("error"))
    root = j["data"]["path"]
    sep = "\\" if "\\" in root else "/"
    target = root.rstrip("\\/") + sep + "jiaozi_smoke.txt"
    st, j = req("POST", "/api/fs/write", {"path": target, "content": "你好，饺子\nhello"})
    ok("写文件", st == 200, j.get("error"))
    st, j = req("GET", "/api/fs/read?path=" + urllib.parse.quote(target))
    ok("读文件内容一致", st == 200 and "你好，饺子" in j["data"]["text"], j.get("error"))
    st, j = req("GET", "/api/fs/search?q=jiaozi_smoke&path=" + urllib.parse.quote(root))
    ok("搜索文件", st == 200 and len(j["data"]) >= 1, j.get("error"))
    st, j = req("POST", "/api/fs/delete", {"path": target})
    ok("删除进回收站", st == 200 and j["data"].get("trashed"), j.get("error"))

    st, j = req("GET", "/api/fs/list?path=" + urllib.parse.quote("/etc"))
    blocked = st in (400, 403, 404)
    ok("越界访问被拦截", blocked, f"status={st} {j.get('error')}")


def test_terminal():
    print("\n[3] 终端（PTY / 管道）")
    events = []
    stop = threading.Event()

    def listen():
        conn = http.client.HTTPConnection(HOST, PORT, timeout=25)
        conn.request("GET", "/api/events")
        r = conn.getresponse()
        while not stop.is_set():
            line = r.readline()
            if not line:
                break
            if line.startswith(b"data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except Exception:
                    pass
        conn.close()

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)

    st, j = req("POST", "/api/term/open", {"cols": 90, "rows": 24})
    ok("创建终端会话", st == 200 and j["data"]["id"], j.get("error"))
    sid = j["data"]["id"]

    # 什么都不输入，也必须很快看到提示符。
    # （曾经这里攒到换行才输出，而 shell 提示符不带换行 → 新终端一片空白）
    deadline = time.time() + 5
    prompt = ""
    while time.time() < deadline:
        prompt = req("GET", f"/api/term/buffer?id={sid}")[1]["data"]["text"]
        if prompt and prompt.rstrip().endswith(("$", "#", ">", "%")):
            break
        time.sleep(0.25)
    ok("打开即有提示符", prompt.rstrip().endswith(("$", "#", ">", "%")), repr(prompt[-60:]))

    req("POST", "/api/term/input", {"id": sid, "data": "echo JIAOZI-TERM-OK\r"})
    deadline = time.time() + 8
    got = ""
    while time.time() < deadline:
        got = "".join(e["d"] for e in events if e.get("t") == "term" and e.get("id") == sid)
        if "JIAOZI-TERM-OK" in got and got.count("JIAOZI-TERM-OK") >= 2:
            break
        time.sleep(0.2)
    ok("命令输出回传", "JIAOZI-TERM-OK" in got, got[-200:])
    req("POST", "/api/term/close", {"id": sid})
    stop.set()
    ok("会话可关闭", True)


def test_agent():
    print("\n[4] Agent 循环（假模型驱动真实工具）")
    st, cfg = req("GET", "/api/config")
    old = cfg["data"]["llm"]
    old_agent = cfg["data"]["agent"]
    st, j = req("POST", "/api/config", {
        "llm": {"base_url": MOCK_URL, "model": "mock-coder",
                "native_tools": True, "stream": True, "max_tokens": 512},
        "agent": {"approval": "auto", "max_steps": 6},
    })
    ok("切换到测试模型", st == 200, j.get("error"))

    st, j = req("GET", "/api/llm/models")
    ok("模型列表可用", st == 200 and "mock-coder" in j["data"], j.get("error"))

    st, j = req("POST", "/api/agent/reset", {"sid": "smoke"})
    seq = []
    try:
        stream_post("/api/agent/chat", {"text": "看看我的目录里有什么", "sid": "smoke"},
                    lambda ev: seq.append(ev))
    except Exception as e:
        ok("对话流式返回", False, e)
        return
    kinds = [e["t"] for e in seq]
    ok("收到流式事件", "delta" in kinds or "tool" in kinds, kinds[:8])
    ok("工具被真实执行", any(e["t"] == "tool" and e.get("status") == "ok" for e in seq))
    tool_ev = [e for e in seq if e["t"] == "tool" and e.get("status") == "ok"]
    ok("工具返回了目录内容", bool(tool_ev) and ("items" in (tool_ev[0].get("result") or "")),
       (tool_ev[0].get("result") if tool_ev else "")[:120])
    done = [e for e in seq if e["t"] == "done"]
    ok("最终回答非空", bool(done) and done[0].get("content"), done[0] if done else "no done")

    # ---- 审批流程 ----
    print("\n[5] 人工审批（危险操作）")
    req("POST", "/api/config", {"agent": {"approval": "always"}})
    req("POST", "/api/agent/reset", {"sid": "smoke2"})
    seen = {"approval": False, "approved": False, "tool_ok": False, "done": False}

    def on_ev(ev):
        if ev["t"] == "approval":
            seen["approval"] = True
            time.sleep(0.15)
            req("POST", "/api/agent/approve", {"id": ev["id"], "ok": True, "sid": "smoke2"})
            seen["approved"] = True
        if ev["t"] == "tool" and ev.get("status") == "ok":
            seen["tool_ok"] = True
        if ev["t"] == "done":
            seen["done"] = True

    try:
        stream_post("/api/agent/chat", {"text": "运行终端测试", "sid": "smoke2"}, on_ev, timeout=90)
    except Exception as e:
        ok("审批流程跑通", False, e)
    ok("触发了审批请求", seen["approval"])
    ok("审批后可执行命令", seen["tool_ok"])
    ok("审批后仍有最终回答", seen["done"])

    # 还原配置（放到全部测试结束后由 main 统一处理）
    return {"llm": old, "agent": old_agent}


def test_device():
    print("\n[6] 设备 / 机器人接口")
    st, j = req("GET", "/api/device/health")
    ok("设备健康检查", st == 200 and j["data"]["brain"] == "online", j.get("error"))
    req("POST", "/api/config", {"llm": {"base_url": MOCK_URL,
                                        "model": "mock-coder", "native_tools": True,
                                        "stream": True},
                                "agent": {"approval": "auto"}})
    st, j = req("POST", "/api/device/task", {"prompt": "看看目录", "device": "smoke-bot"}, timeout=90)
    ok("设备一句话任务", st == 200 and j.get("ok") and j.get("result"),
       j.get("error") or j.get("result"))


def raw(method, path, headers=None, body=None):
    """底层请求：用来验证 token / cookie 这类靠头部的行为。"""
    conn = http.client.HTTPConnection(HOST, PORT, timeout=20)
    payload = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if payload:
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=hdrs)
    r = conn.getresponse()
    data = r.read()
    got = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    return r.status, data, got


def test_image():
    """图像生成：用假端点验证「生成 → 落盘 → 能被文件接口读回」整条链路。"""
    print("\n[6] 图像生成")
    st, j = req("GET", "/api/config")
    orig = (j.get("data") or {}).get("image") or {}
    test_dir = "~/.jiaozi/test-images"

    req("POST", "/api/config", {"image": {
        "enabled": True,
        "base_url": MOCK_URL,
        "model": "mock-image",
        "api_key": "",
        "save_dir": test_dir,
    }})
    try:
        st, j = req("POST", "/api/image/generate", {"prompt": "一张测试图", "n": 2}, timeout=90)
        d = j.get("data") or {}
        files = d.get("files") or []
        ok("生成接口可用", st == 200 and j.get("ok"), j.get("error"))
        ok("按要求生成 2 张", len(files) == 2, files)

        # 用服务端自己的视角判断落盘：测 WSL / 远端设备时，图片在对方磁盘上，
        # 本机的 os.path 根本 stat 不到（会全返回 -1），那测的就不是这回事了。
        sizes = []
        for f in files:
            st2, j2 = req("GET", "/api/fs/stat?path=" + urllib.parse.quote(f))
            size = ((j2.get("data") or {}).get("size") if st2 == 200 else -1)
            sizes.append(size if size is not None else -1)
        ok("图片真的落到磁盘上", bool(sizes) and all(s > 0 for s in sizes), sizes)

        if files:
            conn = http.client.HTTPConnection(HOST, PORT, timeout=15)
            conn.request("GET", "/api/fs/raw?path=" + urllib.parse.quote(files[0]))
            r = conn.getresponse()
            raw = r.read()
            conn.close()
            ok("生成的文件能通过文件接口读回", r.status == 200 and len(raw) > 20, r.status)

        req("POST", "/api/config", {"image": {"enabled": False}})
        st2, j2 = req("POST", "/api/image/generate", {"prompt": "x", "n": 1})
        ok("关闭后明确拒绝、不偷偷请求", st2 >= 400 and not j2.get("ok"), j2)
    finally:
        import glob
        for p in glob.glob(os.path.expanduser(test_dir) + "/*"):
            try:
                os.remove(p)
            except OSError:
                pass
        req("POST", "/api/config", {"image": {
            "enabled": orig.get("enabled", True),
            "base_url": orig.get("base_url", ""),
            "model": orig.get("model", ""),
            "save_dir": orig.get("save_dir") or "~/Pictures/JiaoziAI",
        }})


def test_auth():
    """关掉 localhost 放行，验证 token / cookie / 清单。

    手机连电脑时（服务绑 0.0.0.0）走的就是这条路：首次带 ?token= 打开，
    服务端种 cookie，之后 fetch 与 EventSource 才能通。
    """
    print("\n[7] 鉴权（模拟手机远道访问）")
    tok = TOKEN_ENV
    if not tok:
        try:
            import pathlib
            base = pathlib.Path(os.environ.get("JIAOZI_HOME") or (pathlib.Path.home() / ".jiaozi"))
            tok = json.loads((base / "config.json").read_text(encoding="utf-8"))["auth"]["token"]
        except Exception as e:
            print(f"  跳过：读不到本地 token（{e}）")
            return
    if not tok:
        print("  跳过：未设置 token")
        return

    def set_localhost(flag):
        return raw("POST", "/api/config", {"X-Jiaozi-Token": tok},
                   {"server": {"allow_localhost": flag}})[0]

    try:
        ok("可关闭 localhost 放行", set_localhost(False) == 200)
        time.sleep(0.2)
        ok("无凭据被拒绝", raw("GET", "/api/config")[0] == 401)
        ok("错误 token 被拒绝",
           raw("GET", "/api/config", {"X-Jiaozi-Token": "wrong-" + tok})[0] == 401)
        ok("正确 token 头放行", raw("GET", "/api/config", {"X-Jiaozi-Token": tok})[0] == 200)
        ok("token 参数放行",
           raw("GET", "/api/config?token=" + urllib.parse.quote(tok))[0] == 200)

        st, _, hdrs = raw("GET", "/?token=" + urllib.parse.quote(tok))
        cookie = hdrs.get("set-cookie", "")
        ok("首页下发 cookie", "jz_token=" in cookie, cookie[:70])
        ok("cookie 可持久", "max-age" in cookie.lower(), cookie[:70])
        st, _, _ = raw("GET", "/api/config", {"Cookie": cookie.split(";")[0]})
        ok("cookie 放行", st == 200, st)

        st, body, _ = raw("GET", "/manifest.webmanifest")
        ok("PWA 清单可访问", st == 200, st)
        ok("清单不含 token", tok.encode() not in body)
        ok("清单声明 standalone", b"standalone" in body)
        ok("图标可访问", raw("GET", "/icon.svg")[0] == 200)
        ok("旧 favicon 不报错", raw("GET", "/favicon.ico")[0] in (200, 204))
    finally:
        ok("恢复 localhost 放行", set_localhost(True) == 200)


def main():
    print(f"目标服务: {BASE}")
    try:
        req("GET", "/api/ping", timeout=3)
    except Exception as e:
        print(f"无法连接服务，请先启动：python -m jiaozi --port {PORT}\n{e}")
        return 1

    srv = start_mock()
    print(f"假模型服务: http://127.0.0.1:{MOCK_PORT}/v1")
    saved = None
    try:
        test_core()
        test_fs()
        test_terminal()
        saved = test_agent()
        test_device()
        test_image()
    finally:
        srv.shutdown()
        if saved:
            req("POST", "/api/config", {
                "llm": {"base_url": saved["llm"]["base_url"], "model": saved["llm"]["model"],
                        "native_tools": saved["llm"]["native_tools"],
                        "stream": saved["llm"]["stream"]},
                "agent": {"approval": saved["agent"]["approval"],
                          "max_steps": saved["agent"]["max_steps"]},
            })
    # 鉴权放最后：它会临时关掉 localhost 放行，前面的用例依赖放行
    test_auth()

    total = len(PASS) + len(FAIL)
    print("\n" + "=" * 56)
    print(f"结果：{len(PASS)}/{total} 通过")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
