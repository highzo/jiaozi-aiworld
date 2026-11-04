"""Agent 可调用的工具集。

设计原则：工具就是人类 UI 用的同一批后端 API。
AI 不是"另一个世界"的脚本，而是坐在同一张桌子前的另一个操作者。
"""
from __future__ import annotations

import json
import re
import urllib.request

from .. import config, fsapi, sysinfo
from ..eventbus import BUS
from ..shell import SHELLS

# ---------------------------------------------------------------- 工具声明

def _p(name: str, typ: str, desc: str, required: bool = True, enum=None) -> dict:
    d = {"type": typ, "description": desc}
    if enum:
        d["enum"] = enum
    return d


TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "fs_list", "description": "列出目录内容。用于了解当前环境、找文件。",
        "parameters": {"type": "object", "properties": {
            "path": _p("path", "string", "目录绝对路径，可用 ~ 表示用户主目录；不填为沙箱根目录", False)},
            "required": []}}},
    {"type": "function", "function": {
        "name": "fs_read", "description": "读取文本文件内容。大文件会被截断。",
        "parameters": {"type": "object", "properties": {
            "path": _p("path", "string", "文件绝对路径"),
            "max_bytes": _p("max_bytes", "integer", "最多读取字节数，默认 200000", False)},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "fs_write", "description": "写入/覆盖一个文本文件。会自动创建父目录。",
        "parameters": {"type": "object", "properties": {
            "path": _p("path", "string", "文件绝对路径"),
            "content": _p("content", "string", "完整文件内容")},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "fs_mkdir", "description": "创建目录（含父目录）。",
        "parameters": {"type": "object", "properties": {
            "path": _p("path", "string", "目录绝对路径")}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "fs_search", "description": "按文件名关键词递归搜索。",
        "parameters": {"type": "object", "properties": {
            "query": _p("query", "string", "文件名关键词"),
            "path": _p("path", "string", "搜索起点目录", False),
            "limit": _p("limit", "integer", "最多返回条数，默认 50", False)},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "shell_run", "description": "在系统上执行一条 shell 命令并返回输出。危险操作，重定向/删除需谨慎。",
        "parameters": {"type": "object", "properties": {
            "cmd": _p("cmd", "string", "要执行的完整命令"),
            "cwd": _p("cwd", "string", "工作目录，默认沙箱根目录", False),
            "timeout": _p("timeout", "integer", "超时秒数，默认 60", False)},
            "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "sys_info", "description": "获取系统信息：系统版本、CPU、内存、磁盘、运行时长。",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "proc_list", "description": "列出占用内存最高的进程。",
        "parameters": {"type": "object", "properties": {
            "limit": _p("limit", "integer", "返回条数，默认 20", False)},
            "required": []}}},
    {"type": "function", "function": {
        "name": "proc_kill", "description": "结束一个进程。危险操作。",
        "parameters": {"type": "object", "properties": {
            "pid": _p("pid", "integer", "进程号")}, "required": ["pid"]}}},
    {"type": "function", "function": {
        "name": "ui_open", "description": "在人类正在看的桌面上打开一个应用窗口或文件，让人看到结果。app 可选 files/editor/terminal/monitor/settings/viewer。",
        "parameters": {"type": "object", "properties": {
            "app": _p("app", "string", "应用 id", True,
                      ["files", "editor", "terminal", "monitor", "settings", "viewer"]),
            "path": _p("path", "string", "可选：要打开的路径", False)},
            "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "ui_notify", "description": "在桌面右下角弹出一条通知，向人类汇报进度或结果。",
        "parameters": {"type": "object", "properties": {
            "title": _p("title", "string", "标题"),
            "body": _p("body", "string", "正文")}, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "抓取网页并返回纯文本（需要设备联网）。",
        "parameters": {"type": "object", "properties": {
            "url": _p("url", "string", "http/https 地址")}, "required": ["url"]}}},
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SPECS]

#: 需要人类确认的工具（approval=auto 时生效）
DANGEROUS = {"fs_delete", "shell_run", "proc_kill", "web_fetch"}

#: 会改动系统的工具
WRITE_TOOLS = {"fs_write", "fs_mkdir", "shell_run", "proc_kill", "fs_delete"}

# 保留：fs_delete 未暴露给模型（避免误删），但保留调度实现
_EXTRA_IMPL = {"fs_delete"}


# ---------------------------------------------------------------- 执行

def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n...[已截断，共 {len(s)} 字符]"


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")


def dispatch(name: str, args: dict, ctx: dict | None = None) -> str:
    """执行工具，返回给模型的字符串结果。异常会被转成文本，不打断循环。"""
    ctx = ctx or {}
    cfg = config.load()
    limit = int(cfg["agent"].get("max_output", 8000))
    try:
        if name == "fs_list":
            d = fsapi.list_dir(args.get("path") or None)
            items = [{"name": i["name"], "type": "dir" if i["is_dir"] else i["kind"],
                      "size": i["size"], "path": i["path"]} for i in d["items"][:300]]
            return _truncate(_json({"path": d["path"], "count": len(d["items"]),
                                    "items": items}), limit)

        if name == "fs_read":
            r = fsapi.read_text(args["path"], args.get("max_bytes"))
            return _truncate(f"文件: {r['path']} ({r['size']} bytes)\n---\n{r['text']}", limit)

        if name == "fs_write":
            r = fsapi.write_text(args["path"], args.get("content", ""))
            BUS.publish("fs_change", {"path": r["path"], "action": "write"})
            return _json({"ok": True, **r})

        if name == "fs_mkdir":
            r = fsapi.mkdir(args["path"])
            BUS.publish("fs_change", {"path": r["path"], "action": "mkdir"})
            return _json({"ok": True, "path": r["path"]})

        if name == "fs_search":
            hits = fsapi.search(args.get("path") or None, args["query"],
                                int(args.get("limit") or 50))
            return _truncate(_json({"count": len(hits), "hits": hits[:60]}), limit)

        if name == "fs_delete":
            r = fsapi.delete(args["path"])
            BUS.publish("fs_change", {"path": args["path"], "action": "delete"})
            return _json({"ok": True, **r})

        if name == "shell_run":
            r = SHELLS.run(args["cmd"], cwd=args.get("cwd"),
                           timeout=int(args.get("timeout") or cfg["agent"]["shell_timeout"]),
                           max_output=limit)
            # 让人类在桌面上看见 AI 执行的命令
            BUS.publish("ai_shell", r)
            return f"$ {r['cmd']}\n(exit {r['exit_code']}, {r['duration']}s)\n{_truncate(r['output'], limit)}"

        if name == "sys_info":
            i = sysinfo.info()
            i.pop("app", None)
            return _truncate(_json(i), limit)

        if name == "proc_list":
            return _truncate(_json(sysinfo.processes(int(args.get("limit") or 20))), limit)

        if name == "proc_kill":
            r = sysinfo.kill(int(args["pid"]), force=True)
            return _json(r)

        if name == "ui_open":
            app = args.get("app") or "files"
            path = args.get("path")
            BUS.publish("ui", {"action": "open", "app": app, "path": path})
            return _json({"ok": True, "opened": app, "path": path})

        if name == "ui_notify":
            BUS.notify(args.get("title") or "AI", args.get("body") or "")
            return _json({"ok": True})

        if name == "web_fetch":
            url = args["url"]
            if not url.startswith(("http://", "https://")):
                return "错误：只支持 http/https"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (JiaoziAIWorld)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read(900_000)
            text = raw.decode("utf-8", "replace")
            text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
            text = _HTML_TAG.sub(" ", text)
            text = _WS.sub("\n\n", text)
            text = re.sub(r"[ \t]{2,}", " ", text).strip()
            return _truncate(f"URL: {url}\n\n{text}", limit)

        return f"错误：未知工具 {name}"
    except fsapi.FSError as e:
        return f"错误：{e}"
    except KeyError as e:
        return f"错误：缺少参数 {e}"
    except Exception as e:  # noqa: BLE001
        return f"错误：{type(e).__name__}: {e}"


def tool_summary(name: str, args: dict) -> str:
    """给 UI 显示的一句话摘要。"""
    a = args or {}
    if name == "fs_list":
        return f"浏览 {a.get('path', '根目录')}"
    if name == "fs_read":
        return f"读取 {a.get('path', '')}"
    if name == "fs_write":
        return f"写入 {a.get('path', '')}"
    if name == "fs_mkdir":
        return f"新建目录 {a.get('path', '')}"
    if name == "fs_search":
        return f"搜索「{a.get('query', '')}」"
    if name == "shell_run":
        return f"执行命令 {a.get('cmd', '')[:80]}"
    if name == "sys_info":
        return "读取系统信息"
    if name == "proc_list":
        return "查看进程"
    if name == "proc_kill":
        return f"结束进程 {a.get('pid')}"
    if name == "ui_open":
        return f"打开 {a.get('app')} {a.get('path') or ''}".strip()
    if name == "ui_notify":
        return f"通知：{a.get('title', '')}"
    if name == "web_fetch":
        return f"抓取 {a.get('url', '')}"
    return name
