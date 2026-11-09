"""Agent 可调用的工具集。

设计原则：工具就是人类 UI 用的同一批后端 API。
AI 不是"另一个世界"的脚本，而是坐在同一张桌子前的另一个操作者。
"""
from __future__ import annotations

import json
import re
import urllib.request

from .. import config, esp, fsapi, peer, sysinfo
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
        "name": "image_gen", "description": "用文生图模型画图，把结果保存成图片文件。想让人「看到」任何视觉内容时用它（插画、头像、海报、示意图、产品图）。中文提示词可直接用，描述越具体越好：主体、构图、光线、风格、色彩。",
        "parameters": {"type": "object", "properties": {
            "prompt": _p("prompt", "string", "画面描述，中文即可。只描述一个画面，不要写「第一张…第二张…」"),
            "n": _p("n", "integer", "同一个画面的变体数量，1-4，默认 1。要不同场景请分多次调用", False),
            "size": _p("size", "string", "尺寸如 1024x1024 / 1024x1536，留空用默认", False)},
            "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "抓取网页并返回纯文本（需要设备联网）。",
        "parameters": {"type": "object", "properties": {
            "url": _p("url", "string", "http/https 地址")}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "peer_list", "description": "列出同一个局域网里我认得的设备（已配对的 + 刚被发现的），含在线状态和能力。想知道「除了这台机器，我还能指挥谁」时用它。",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "peer_call",
        "description": "在局域网里的另一台设备上执行一个工具：比如在客厅的电脑上读文件、跑命令、打开窗口。只对已配对的设备有效；device 填 peer_list 里的 id 或名字。",
        "parameters": {"type": "object", "properties": {
            "device": _p("device", "string", "目标设备的 id 或名字，见 peer_list"),
            "tool": _p("tool", "string", "在那个设备上执行的工具名，如 fs_list / shell_run / ui_open"),
            "args": {"type": "object", "description": "那个工具需要的参数，按它的参数表填，没有就空对象"}},
            "required": ["device", "tool"]}}},
    {"type": "function", "function": {
        "name": "esp_devices",
        "description": "列出家里接进来的小设备（ESP32 开关、插座、继电器、红外遥控），含在线状态、通道（每个通道就是一路开关）、传感器读数。要开关灯、插座、风扇之前先用它。",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "esp_state",
        "description": "读某台家电设备的当前状态：每路开关是开还是关、传感器数值、在线多久。",
        "parameters": {"type": "object", "properties": {
            "device": _p("device", "string", "设备 id 或名字，见 esp_devices")},
            "required": ["device"]}}},
    {"type": "function", "function": {
        "name": "esp_control",
        "description": "开关家电。device 填设备名或 id，channel 填那台设备的某一路（比如 r1），on 填 true/false 表示开或关；只切换就用 toggle=true；红外遥控类设备用 action 指令。说\"把客厅灯打开\"时用它。",
        "parameters": {"type": "object", "properties": {
            "device": _p("device", "string", "设备 id 或名字"),
            "channel": _p("channel", "string", "通道 id，如 r1；设备只有一路时可以留空", False),
            "on": _p("on", "boolean", "true=开，false=关", False),
            "toggle": _p("toggle", "boolean", "切换当前状态（开变关、关变开）", False),
            "action": _p("action", "string", "给红外/自定义设备用的动作名，如 ac_on / tv_off", False)},
            "required": ["device"]}}},
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SPECS]

#: 需要人类确认的工具（approval=auto 时生效）
DANGEROUS = {"fs_delete", "shell_run", "proc_kill", "web_fetch", "peer_call"}

#: 会改动系统的工具
WRITE_TOOLS = {"fs_write", "fs_mkdir", "shell_run", "proc_kill", "fs_delete"}

# 保留：fs_delete 未暴露给模型（避免误删），但保留调度实现
_EXTRA_IMPL = {"fs_delete"}


# ---------------------------------------------------------------- 执行

def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n...[已截断，共 {len(s)} 字符]"


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def resolve_peer(target: str) -> str:
    """把「设备名」或 id 解析成 peer id。名字允许唯一子串匹配。"""
    target = (target or "").strip()
    if not target:
        return ""
    peers = peer.snapshot().get("peers") or []
    for p in peers:
        if p.get("id") == target:
            return p["id"]
    low = target.lower()
    for p in peers:
        if p.get("paired") and (p.get("name") or "").lower() == low:
            return p["id"]
    hits = [p for p in peers
            if p.get("paired") and low in (p.get("name") or "").lower()]
    return hits[0]["id"] if len(hits) == 1 else ""


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

        if name == "image_gen":
            from . import imagegen
            try:
                r = imagegen.generate(
                    args.get("prompt") or "", int(args.get("n") or 1),
                    args.get("size") or "", cfg=cfg)
            except imagegen.ImageError as e:
                msg = str(e)
                if e.raw:
                    msg += f"\n接口原文: {e.raw[:300]}"
                return f"生成失败：{msg}\n（提示：到「设置 → 图像」检查接口地址 / 模型 / API Key）"
            for f in r["files"]:
                BUS.publish("fs_change", {"path": f, "action": "write"})
            BUS.notify("图片已生成", f"{len(r['files'])} 张，用时 {r['elapsed']}s")
            return _json({"ok": True, **r})

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

        if name == "peer_list":
            s = peer.snapshot()
            me = s.get("me") or {}
            rows = [{"id": p["id"], "name": p["name"], "online": p["online"],
                     "paired": p["paired"], "ip": p.get("ip"), "port": p.get("port"),
                     "caps": p.get("caps") or []} for p in s.get("peers") or []]
            return _truncate(_json({
                "me": {"name": me.get("name"), "ips": me.get("ips"),
                       "discovery": me.get("discovery")},
                "count": len(rows), "peers": rows}), limit)

        if name == "peer_call":
            target = str(args.get("device") or "").strip()
            tool = str(args.get("tool") or "").strip()
            a = args.get("args")
            if isinstance(a, str):  # 小模型常把对象写成字符串
                try:
                    a = json.loads(a)
                except Exception:
                    a = {}
            if not isinstance(a, dict):
                a = {}
            if not target or not tool:
                return "错误：需要 device（设备 id 或名字）和 tool（工具名）"
            pid = resolve_peer(target)
            if not pid:
                names = [p["name"] for p in peer.snapshot().get("peers") or []
                         if p.get("paired")]
                return (f"错误：没有唯一匹配「{target}」的已配对设备。"
                        f"当前已配对: {names or '无'}，先用 peer_list 看看")
            r = peer.call(pid, tool, a)
            return _truncate(_json({"device": peer.peer_name(pid), **r}), limit)

        if name == "esp_devices":
            s = esp.snapshot()
            rows = [{"id": d["id"], "name": d["name"], "online": d.get("online"),
                     "ip": d.get("host"), "port": d.get("port"),
                     "channels": [{"id": c["id"], "name": c["name"], "type": c["type"]}
                                  for c in d.get("channels") or []]}
                    for d in s["devices"]]
            if not rows:
                return ("还没有接入任何家电设备。可以：1) 在「家电」里点搜索；"
                        "2) 手填设备 IP 添加；3) 没有硬件时先跑 tools/esp_sim.py 模拟一台。")
            return _truncate(_json({"count": s["count"], "online": s["online"],
                                    "devices": rows}), limit)

        if name == "esp_state":
            dev = esp.resolve(str(args.get("device") or ""))
            if not dev:
                raise esp.EspError("没有唯一匹配的设备，先用 esp_devices 看看")
            data = esp.state(dev["id"])
            return _truncate(_json({"device": dev["name"], **data}), limit)

        if name == "esp_control":
            target = str(args.get("device") or "").strip()
            if not target:
                return "错误：需要 device（设备名或 id）"
            dev = esp.resolve(target)
            if not dev:
                names = [d["name"] for d in esp.snapshot(ping=False)["devices"]]
                return f"错误：没有唯一匹配「{target}」的设备。当前有：{names or '无'}"
            channel = str(args.get("channel") or "").strip()
            if not channel and len(dev.get("channels") or []) == 1 and not args.get("action"):
                channel = dev["channels"][0]["id"]
            if not channel and not args.get("action"):
                opts = [f"{c['id']}={c['name']}" for c in dev.get("channels") or []]
                return f"错误：{dev['name']} 有多路，要指定 channel（{'、'.join(opts)}）"
            on = args.get("on")
            if isinstance(on, str):
                on = on.strip().lower() in ("1", "true", "on", "yes", "开", "打开")
            data = esp.control(dev["id"], channel=channel, on=on,
                               toggle=bool(args.get("toggle")),
                               action=str(args.get("action") or ""))
            return _truncate(_json({"device": dev["name"], "channel": channel,
                                    "result": data}), limit)

        return f"错误：未知工具 {name}"
    except fsapi.FSError as e:
        return f"错误：{e}"
    except esp.EspError as e:
        return f"错误：{e.msg}"
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
    if name == "peer_list":
        return "查看局域网里的设备"
    if name == "peer_call":
        return f"在 {a.get('device', '')} 上执行 {a.get('tool', '')}"
    if name == "esp_devices":
        return "查看家电设备"
    if name == "esp_state":
        return f"读取 {a.get('device', '')} 的状态"
    if name == "esp_control":
        if a.get("toggle"):
            act = "切换"
        elif a.get("action"):
            act = str(a.get("action"))
        else:
            act = "打开" if a.get("on") else "关闭"
        return f"{act} {a.get('device', '')} {a.get('channel') or ''}".strip()
    return name
