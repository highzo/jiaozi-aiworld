#!/usr/bin/env python3
"""体检：手机连不上、设备搜不到的时候，先跑这个。

它不修东西，只把「现在到底卡在哪一层」摆出来：
端口占没占、防火墙放没放、组播能不能收、代理有没有拦回环、
本机 IP 是哪几个、已经配对/接入了什么。

    python3 tools/doctor.py
    python3 tools/doctor.py --port 8787      # 换端口
    python3 tools/doctor.py --json           # 给脚本用

输出里每一项都是 ✅ 正常 / ⚠️ 能跑但要注意 / ❌ 这里断了。
❌ 那几行后面直接写了「怎么办」。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OK, WARN, BAD = "✅", "⚠️", "❌"
rows: list[dict] = []


def add(state: str, title: str, detail: str = "", fix: str = "") -> None:
    rows.append({"state": state, "title": title, "detail": detail, "fix": fix})


# ---------------------------------------------------------------- 各项检查

def check_python() -> None:
    v = sys.version_info
    if v >= (3, 8):
        add(OK, "Python 版本", f"{v.major}.{v.minor}.{v.micro}")
    else:
        add(BAD, "Python 版本", f"{v.major}.{v.minor}，需要 3.8+",
            "装一个 3.8 以上的 Python 再来")


def check_proxy() -> None:
    keys = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY")
    hit = {k: os.environ[k] for k in keys if os.environ.get(k)}
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    if not hit:
        add(OK, "代理环境变量", "没有设置，不会误拦内网请求")
        return
    loopback_ok = ("127.0.0.1" in no_proxy) and ("localhost" in no_proxy)
    if loopback_ok:
        add(OK, "代理环境变量", f"有代理但 no_proxy 已包含回环：{', '.join(hit)}")
    else:
        add(WARN, "代理会拦回环地址", f"{', '.join(hit)}；no_proxy={no_proxy or '空'}",
            "给 no_proxy 加上 127.0.0.1,localhost —— 否则本机请求也会被送进代理，"
            "表现就是「Chrome 起不来」「接口 502」")


def check_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    if ips:
        add(OK, "本机局域网 IP", "  ".join(ips))
    else:
        add(BAD, "本机局域网 IP", "一个都没拿到", "确认 Wi-Fi / 网线是通的")
    return ips


def check_ports(port: int) -> None:
    for name, p, why in (("HTTP 服务", port, "手机通过这个端口打开桌面"),
                         ("互认发现", 8788, "电脑之间互相看得见"),
                         ("家电发现", 8789, "ESP32 自动出现")):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.8)
        busy = s.connect_ex(("127.0.0.1", p)) == 0
        s.close()
        if p == port:
            add(OK if busy else WARN, f"{name} :{p}",
                "已经在监听（服务开着）" if busy else "没有服务在监听",
                "" if busy else "先启动：python3 -m jiaozi --host 0.0.0.0")
        else:
            add(WARN if busy else OK, f"{name} :{p}",
                "被占用" if busy else "空闲",
                "" if not busy else "换一个端口，或者关掉占用的程序")


def check_udp(port: int = 8789) -> None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))
        s.close()
        add(OK, f"UDP {port} 可绑定", "能收发现包")
    except OSError as e:
        add(WARN, f"UDP {port} 绑不上", str(e),
            "多半是已经开着一个饺子在占这个端口；不影响手填 IP 添加设备")


def check_self(port: int) -> None:
    try:
        with OPENER.open(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            body = json.loads(r.read() or b"{}")
        add(OK, "本机自访问", f"HTTP {r.status} {body.get('data', {}).get('version', '')}".strip())
    except Exception as e:  # noqa: BLE001
        add(WARN, "本机自访问", f"{type(e).__name__}: {e}",
            "服务没起，或者起在了别的端口（--port）")


def check_firewall() -> None:
    if os.name != "nt":
        if sys.platform.startswith("linux"):
            has_ufw = os.path.exists("/usr/sbin/ufw") or os.path.exists("/usr/bin/ufw")
            add(WARN if has_ufw else OK, "防火墙",
                "检测到 ufw，确认放行 8787-8789 tcp/udp" if has_ufw else "没检测到 ufw")
        else:
            add(OK, "防火墙", "非 Windows，跳过")
        return
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "show", "currentprofile"],
            capture_output=True, text=True, timeout=8,
            encoding="gbk", errors="replace")
        text = out.stdout or ""
        on = "ON" in text.upper() or "启用" in text or "打开" in text
        add(WARN if on else OK, "Windows 防火墙",
            "开着" if on else "关着",
            "开着也不代表连不上，但要放行一次：以管理员运行 "
            "scripts/win-firewall.ps1，或者在「允许应用通过防火墙」里勾上 Python" if on else "")
    except Exception as e:  # noqa: BLE001
        add(WARN, "Windows 防火墙", f"查不到（{type(e).__name__}）", "手动看一眼防火墙设置")


def check_state() -> None:
    try:
        from jiaozi import config, esp, peer
    except Exception as e:  # noqa: BLE001
        add(BAD, "读取项目配置", f"{type(e).__name__}: {e}",
            "确认是在项目根目录跑的；或者 PYTHONPATH 指到仓库根")
        return
    try:
        cfg = config.load()
        add(OK, "数据目录", str(config.DATA_DIR))
    except Exception as e:  # noqa: BLE001
        add(BAD, "读取配置", str(e))
        return

    host = cfg["server"].get("host")
    if host in ("0.0.0.0", "::", ""):
        add(OK, "监听地址", f"{host}（局域网可达）")
    else:
        add(BAD, "只监听回环", f"{host}",
            "手机连不上就是因为这个：加 --host 0.0.0.0 重启")

    try:
        ps = peer.snapshot()
        paired = [p for p in (ps.get("peers") or []) if p.get("paired")]
        add(OK if paired else WARN, "已配对设备",
            f"{len(paired)} 台：" + "、".join(p["name"] for p in paired) if paired
            else "还没有配对任何设备",
            "" if paired else "在「设备」里生成配对码，另一台输入 6 位数字")
    except Exception as e:  # noqa: BLE001
        add(WARN, "配对表", f"读不到（{type(e).__name__}）")

    try:
        es = esp.snapshot(ping=False)
        n = es.get("count") or 0
        add(OK if n else WARN, "已接入家电", f"{n} 台" if n else "还没有设备",
            "" if n else "在「家电」里搜索；或先跑 tools/esp_sim.py 模拟一台")
    except Exception as e:  # noqa: BLE001
        add(WARN, "家电表", f"读不到（{type(e).__name__}）")


# ---------------------------------------------------------------- 输出

def main() -> int:
    ap = argparse.ArgumentParser(description="饺子AIWorld 联调体检")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    check_python()
    check_proxy()
    ips = check_ips()
    check_ports(args.port)
    check_udp()
    check_self(args.port)
    check_firewall()
    check_state()

    if args.json:
        print(json.dumps({"rows": rows, "ips": ips, "port": args.port},
                         ensure_ascii=False, indent=2))
        return 0 if all(r["state"] != BAD for r in rows) else 1

    print("=" * 66)
    print("  饺子AIWorld · 联调体检")
    print("=" * 66)
    for r in rows:
        print(f"{r['state']} {r['title']:<22} {r['detail']}")
        if r["fix"]:
            print(f"       ↳ {r['fix']}")
    bad = [r for r in rows if r["state"] == BAD]
    warn = [r for r in rows if r["state"] == WARN]
    print("-" * 66)
    if bad:
        print(f"有 {len(bad)} 项断了（❌），先解决它们，其余检查意义不大。")
    elif warn:
        print(f"没有硬伤，{len(warn)} 项需要注意（⚠️），通常不影响基本使用。")
    else:
        print("全绿。手机用上面的局域网 IP + ?token=… 打开就能进。")
    if ips:
        print(f"手机访问：http://{ips[0]}:{args.port}/")
        print("（第一次会要求带 token；地址栏后面加 ?token=<配置里的 auth.token>）")
    print("=" * 66)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
