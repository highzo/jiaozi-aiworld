#!/usr/bin/env python3
"""ESP32 模拟器：没有硬件也能把「家电」这一整套跑通。

它做的事和固件一模一样——开机往局域网里喊一声身份，然后等电脑来问状态、
下命令。所以用它验证过的流程，换成真板子只差改一个 IP。

用法：

    # 一台两路的「客厅灯」
    python3 tools/esp_sim.py --id esp32-a1b2 --name 客厅灯 --channels r1:灯,r2:风扇

    # 换端口、加访问密钥
    python3 tools/esp_sim.py --id esp32-c3d4 --name 卧室 --http-port 8081 --key 1234

    # 只喊不监听（同一台机器上起多台模拟器时用，避免抢 8789 端口）
    python3 tools/esp_sim.py --id esp32-e5f6 --name 空调 --no-listen

模拟器会把自己收到过的命令打印出来，方便一边点界面一边看「到底发没发出去」。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GROUP = "239.255.77.88"
UDP_PORT = 8789
PROTO = 1


class Device:
    def __init__(self, did: str, name: str, channels: list[tuple[str, str, str]],
                 key: str = "", model: str = "esp32-sim", fw: str = "sim-1.0"):
        self.id = did
        self.name = name
        self.key = key
        self.model = model
        self.fw = fw
        self.boot = time.time()
        self.channels: dict[str, dict] = {}
        for cid, cname, ctype in channels:
            self.channels[cid] = {"name": cname, "type": ctype, "on": False}
        self.lock = threading.Lock()
        self.cmds = 0

    def info(self) -> dict:
        return {
            "id": self.id, "name": self.name, "model": self.model, "fw": self.fw,
            "proto": PROTO, "ip": local_ip(),
            "caps": sorted({c["type"] for c in self.channels.values()} | {"sensor"}),
            "channels": [{"id": k, "name": v["name"], "type": v["type"]}
                         for k, v in self.channels.items()],
        }

    def state(self) -> dict:
        with self.lock:
            return {
                "channels": {k: dict(v) for k, v in self.channels.items()},
                # 假的温度：让它随时间的正弦动，界面上能看出「在跳」
                "sensors": {"temp": round(24 + 2.5 * ((time.time() % 60) / 60 - 0.5), 1)},
                "uptime": int(time.time() - self.boot),
                "rssi": -52,
            }

    def apply(self, body: dict) -> dict:
        with self.lock:
            cid = str(body.get("channel") or "")
            if body.get("action"):
                self.cmds += 1
                return {"ok": True, "action": body["action"], "channels": self._plain()}
            if cid not in self.channels:
                raise ValueError(f"没有通道 {cid}")
            ch = self.channels[cid]
            if body.get("on") is not None:
                ch["on"] = bool(body["on"])
            elif body.get("toggle"):
                ch["on"] = not ch["on"]
            else:
                raise ValueError("需要 on 或 toggle")
            self.cmds += 1
            return {"channel": cid, "on": ch["on"], "channels": self._plain()}

    def _plain(self) -> dict:
        return {k: v["on"] for k, v in self.channels.items()}


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_handler(dev: Device):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "JiaoziESP32Sim/1.0"

        def log_message(self, fmt, *args):  # 别把每条请求都刷到终端
            pass

        def _send(self, obj, code=200):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _auth(self) -> bool:
            if not dev.key:
                return True
            if self.headers.get("X-JZ-Key") == dev.key:
                return True
            self._send({"ok": False, "error": "密钥不对"}, 401)
            return False

        def do_GET(self):
            if not self._auth():
                return
            path = self.path.split("?")[0]
            if path == "/api/info":
                self._send({"ok": True, "data": dev.info()})
            elif path == "/api/state":
                self._send({"ok": True, "data": dev.state()})
            elif path == "/":
                self._send({"ok": True, "data": {"name": dev.name, "id": dev.id}})
            else:
                self._send({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            if not self._auth():
                return
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                body = json.loads(raw.decode("utf-8", "replace") or "{}")
                if not isinstance(body, dict):
                    raise ValueError("body 必须是对象")
            except ValueError as e:
                self._send({"ok": False, "error": str(e)}, 400)
                return
            path = self.path.split("?")[0]
            if path != "/api/cmd":
                self._send({"ok": False, "error": "not found"}, 404)
                return
            try:
                data = dev.apply(body)
            except ValueError as e:
                self._send({"ok": False, "error": str(e)}, 400)
                return
            print(f"[{dev.name}] 收到命令 {json.dumps(body, ensure_ascii=False)} "
                  f"→ {json.dumps(data.get('channels', {}), ensure_ascii=False)}", flush=True)
            self._send({"ok": True, "data": data})

    return H


def announce_loop(dev: Device, udp_port: int, stop: threading.Event,
                  listen_sock: socket.socket | None) -> None:
    """每秒喊一次身份；同时把收到的 esp.find 回话（真板子也是这么干的）。"""
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if listen_sock is not None:
        listen_sock.settimeout(0.5)

    def packet() -> bytes:
        d = dev.info()
        d.update({"proto": PROTO, "t": "esp.announce", "port": dev_port[0]})
        return json.dumps(d, ensure_ascii=False).encode("utf-8")

    def shout(raw: bytes, to: str) -> None:
        try:
            tx.sendto(raw, (to, udp_port))
        except OSError:
            pass

    last = 0.0
    while not stop.is_set():
        now = time.time()
        if now - last >= 1.0:
            last = now
            raw = packet()
            shout(raw, GROUP)
            shout(raw, "255.255.255.255")
        if listen_sock is not None:
            try:
                data, addr = listen_sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            try:
                pkt = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(pkt, dict) and pkt.get("t") == "esp.find":
                shout(packet(), addr[0])  # 谁问的，单独回给谁
    tx.close()


dev_port = [80]


def main() -> int:
    ap = argparse.ArgumentParser(description="ESP32 家电模拟器")
    ap.add_argument("--id", default="esp32-sim01", help="设备唯一 id")
    ap.add_argument("--name", default="模拟插座", help="显示名")
    ap.add_argument("--channels", default="r1:继电器1,r2:继电器2",
                    help="通道表，形如 r1:灯,r2:风扇")
    ap.add_argument("--http-port", type=int, default=8080, help="假装是板子的 HTTP 端口")
    ap.add_argument("--key", default="", help="访问密钥（对应固件里的 JZ_KEY）")
    ap.add_argument("--udp-port", type=int, default=UDP_PORT, help="发现端口，和主程序保持一致")
    ap.add_argument("--no-listen", action="store_true",
                    help="不监听发现包（同机多开时用，避免抢端口）")
    args = ap.parse_args()

    chans = []
    for part in args.channels.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        cid = bits[0].strip()
        cname = bits[1].strip() if len(bits) > 1 else cid
        ctype = bits[2].strip() if len(bits) > 2 else "relay"
        chans.append((cid, cname, ctype))
    if not chans:
        chans = [("r1", "继电器1", "relay")]

    dev = Device(args.id, args.name, chans, key=args.key)
    dev_port[0] = args.http_port

    listen_sock = None
    if not args.no_listen:
        try:
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            listen_sock.bind(("", args.udp_port))
            mreq = socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0")
            try:
                listen_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
        except OSError as e:
            print(f"[warn] 发现端口 {args.udp_port} 监听失败（{e}），改用只广播模式",
                  file=sys.stderr)
            listen_sock = None

    srv = ThreadingHTTPServer(("0.0.0.0", args.http_port), make_handler(dev))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    stop = threading.Event()
    threading.Thread(target=announce_loop, daemon=True,
                     args=(dev, args.udp_port, stop, listen_sock)).start()

    print(f"[{dev.name}] 已上线  id={dev.id}")
    print(f"  HTTP  http://{local_ip()}:{args.http_port}/api/info")
    print(f"  通道  {', '.join(c[0] + '=' + c[1] for c in chans)}")
    print(f"  发现  UDP {args.udp_port} {'（可响应搜索）' if listen_sock else '（只广播）'}")
    print("  Ctrl+C 退出")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.shutdown()
        if listen_sock is not None:
            listen_sock.close()
        print(f"\n[{dev.name}] 已下线，共处理 {dev.cmds} 条命令")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
