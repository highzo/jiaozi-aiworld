"""家电：把 ESP32 这类小设备接进桌子，让人和 AI 用同一套动作开关它们。

为什么不让 ESP32 反过来连服务器：单片机的固件越薄越不容易变砖。
所以约定反过来——**ESP32 只做三件事**：

1. 开机往局域网里喊一声「我是谁、我能干什么」（UDP，1 秒一次）；
2. 提供一个米粒大的 HTTP 接口（``/api/info`` / ``/api/state`` / ``/api/cmd``）；
3. 剩下的全交给电脑：发现也由电脑主动喊一声 ``esp.find``，设备听到再回话。

这样固件里没有重连逻辑、没有长连接、没有心跳超时。
断电再插上，三秒后自己就回来了。

**为什么不让手机直连 ESP32**：手机浏览器会拦跨域请求，ESP32 上跑 CORS
又得处理预检。统一走电脑这一跳，手机只跟一个源打交道，
同一套页面在电脑和手机上就都能遥控。

协议版本统一放在 ``proto`` 字段里，设备回话时版本对不上就丢弃并记一条日志，
不会把畸形数据混进状态表。
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

from . import config

#: 和互认用的 239.255.77.87 错开
GROUP = "239.255.77.88"
UDP_PORT = 8789
PROTO = 1
ANNOUNCE_TTL = 90.0     # 超过这么久没听到，就当它离线
PROBE_TTL = 6.0         # 在线状态缓存，避免每开一次面板就打一遍设备
HTTP_TIMEOUT = 2.0

_lock = threading.RLock()
_devices: dict[str, dict] = {}
_sock: socket.socket | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_udp_port = UDP_PORT
_listening = False
_err = ""
_seen_count = 0
_last_packet = 0.0
_probe_cache: dict[str, tuple[float, bool]] = {}

#: 回环地址不该经过代理；这台开发机的 http_proxy 曾经把 127.0.0.1 也送出去过
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class EspError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.msg = msg
        self.code = code


# ------------------------------------------------------------------ 存档

def _path():
    return config.DATA_DIR / "esp.json"


def _load() -> None:
    with _lock:
        if _devices:
            return
        try:
            raw = json.loads(_path().read_text("utf-8"))
        except (OSError, ValueError):
            return
        items = raw.get("devices") if isinstance(raw, dict) else None
        if isinstance(items, dict):
            for k, v in items.items():
                if isinstance(v, dict) and v.get("host"):
                    v.setdefault("id", k)
                    _devices[k] = v


def _save() -> None:
    with _lock:
        raw = {"version": 1, "devices": _devices}
    try:
        p = _path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[esp] 写入 {_path()} 失败：{e}")


# ------------------------------------------------------------------ 发现

def _pick(pkt: dict, host: str) -> None:
    """把一条 announce 收进表里。字段名做一次收敛，缺什么补什么。"""
    did = str(pkt.get("id") or "").strip()
    if not did:
        return
    try:
        proto = int(pkt.get("proto") or 0)
    except (TypeError, ValueError):
        proto = 0
    if proto != PROTO:
        print(f"[esp] 忽略协议版本 {proto} 的设备 {did}")
        return

    chans = []
    for c in (pkt.get("channels") or [])[:12]:
        if isinstance(c, dict) and c.get("id"):
            chans.append({"id": str(c["id"]), "name": str(c.get("name") or c["id"]),
                          "type": str(c.get("type") or "relay")})
    caps = [str(x) for x in (pkt.get("caps") or [])][:12] or ["relay"]

    with _lock:
        old = _devices.get(did) or {}
        dev = {
            "id": did,
            "name": old.get("alias") or str(pkt.get("name") or did),
            "alias": old.get("alias") or "",
            "host": host,
            "port": int(pkt.get("port") or old.get("port") or 80),
            "key": old.get("key") or "",
            "model": str(pkt.get("model") or old.get("model") or ""),
            "fw": str(pkt.get("fw") or old.get("fw") or ""),
            "caps": caps,
            "channels": chans or old.get("channels") or [],
            "ip": host,
            "source": old.get("source") or "udp",
            "added_at": old.get("added_at") or int(time.time()),
            "last_seen": int(time.time()),
        }
        _devices[did] = dev
    _save()


def _listen() -> None:
    global _listening, _err, _seen_count, _last_packet
    while not _stop.is_set():
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind(("", _udp_port))
            mreq = socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0")
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass  # 组播加不进去也能收广播包，不致命
            s.settimeout(1.0)
            _listening = True
            _err = ""
            while not _stop.is_set():
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                _seen_count += 1
                _last_packet = time.time()
                try:
                    pkt = json.loads(data.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(pkt, dict) and pkt.get("t") == "esp.announce":
                    _pick(pkt, addr[0])
        except OSError as e:
            _listening = False
            _err = f"{e}"
            if _stop.is_set():
                break
            time.sleep(3.0)  # 端口被占 / 安卓权限问题：等一会再试，别刷屏
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
    _listening = False


def start(port: int = UDP_PORT) -> bool:
    global _thread, _udp_port
    _load()
    with _lock:
        if _thread and _thread.is_alive():
            return _listening
        _udp_port = port
        _stop.clear()
        _thread = threading.Thread(target=_listen, name="esp-udp", daemon=True)
        _thread.start()
    for _ in range(20):
        if _listening:
            break
        time.sleep(0.05)
    return _listening


def stop() -> None:
    _stop.set()


def _tx(payload: dict) -> None:
    """喊一嗓子。组播 + 广播各发一遍：有的 AP 只放过其中一种。"""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if hasattr(socket, "IP_MULTICAST_TTL"):
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            except OSError:
                pass
        for addr in ((GROUP, _udp_port), ("255.255.255.255", _udp_port)):
            try:
                s.sendto(raw, addr)
            except OSError:
                pass
    finally:
        s.close()


def scan(wait: float = 1.6, rounds: int = 3) -> dict:
    """主动搜一轮。重复发几遍——2.4G 上丢广播包是常态。"""
    before = len(_devices)
    for _ in range(max(1, rounds)):
        _tx({"proto": PROTO, "t": "esp.find", "from": socket.gethostname()})
        time.sleep(wait / max(1, rounds))
    return {"found": len(_devices), "new": len(_devices) - before}


# ------------------------------------------------------------------ HTTP 调用

def _req(dev: dict, path: str, body: dict | None = None, timeout: float = HTTP_TIMEOUT) -> dict:
    host = str(dev.get("host") or "").strip()
    if not host:
        raise EspError("设备没有地址")
    port = int(dev.get("port") or 80)
    url = f"http://{host}:{port}{path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": f"JiaoziAIWorld/{config.VERSION}"}
    if dev.get("key"):
        headers["X-JZ-Key"] = str(dev["key"])
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            raw = r.read(65536)
        out = json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # 401/403 单独保留状态码：说明「设备是活的，只是不让我进」，
        # 和「设备根本连不上」是两件事——在线判断要用到这个区别。
        raise EspError(f"设备返回 {e.code}", e.code if e.code in (401, 403) else 502) from None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise EspError(f"连不上 {host}:{port}（{getattr(e, 'reason', e)}）", 502) from None
    except ValueError:
        raise EspError("设备回的不是 JSON", 502) from None
    if not isinstance(out, dict):
        raise EspError("设备回的 JSON 不是对象", 502)
    if out.get("ok") is False:
        raise EspError(str(out.get("error") or "设备拒绝执行"), 502)
    return out.get("data") if isinstance(out.get("data"), dict) else out


def _online(dev: dict) -> bool:
    did = dev.get("id") or ""
    now = time.time()
    hit = _probe_cache.get(did)
    if hit and now - hit[0] < PROBE_TTL:
        return hit[1]
    ok = True
    try:
        _req(dev, "/api/info", timeout=1.2)
    except EspError as e:
        # 需要密钥的设备在没配密钥前会回 401。它在网里活着，只是还不让进，
        # 这种情况必须算「在线」——否则用户会以为设备没通电。
        ok = e.code in (401, 403)
    _probe_cache[did] = (now, ok)
    if ok:
        with _lock:
            if did in _devices:
                _devices[did]["last_seen"] = int(now)
    return ok


# ------------------------------------------------------------------ 对外

def snapshot(ping: bool = True) -> dict:
    _load()
    with _lock:
        items = [dict(d) for d in _devices.values()]
    out = []
    now = time.time()
    for d in items:
        if ping:
            d["online"] = _online(d)
        else:
            d["online"] = (now - float(d.get("last_seen") or 0)) < ANNOUNCE_TTL
        out.append(d)
    out.sort(key=lambda x: (not x.get("online"), str(x.get("name") or "")))
    return {
        "devices": out,
        "count": len(out),
        "online": sum(1 for d in out if d["online"]),
        "listening": _listening,
        "error": _err,
        "udp_port": _udp_port,
        "seen_packets": _seen_count,
        "last_packet": int(_last_packet) if _last_packet else 0,
    }


def resolve(target: str) -> dict | None:
    """按 id 或名字找设备；名字重复时返回 None，让调用方去问人。"""
    t = str(target or "").strip()
    if not t:
        return None
    _load()
    with _lock:
        if t in _devices:
            return dict(_devices[t])
        hits = [d for d in _devices.values()
                if t in (str(d.get("name") or ""), str(d.get("alias") or ""))]
    return dict(hits[0]) if len(hits) == 1 else None


def add(host: str, port: int = 80, key: str = "", name: str = "") -> dict:
    """手动添加：直接问设备要身份，绕开发现（公共 WiFi 常禁组播）。"""
    host = str(host or "").strip()
    if not host:
        raise EspError("需要设备 IP")
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        raise EspError("端口不对") from None
    probe = {"host": host, "port": port, "key": key}
    info = _req(probe, "/api/info", timeout=3.0)
    did = str(info.get("id") or f"{host}:{port}")
    chans = [{"id": str(c["id"]), "name": str(c.get("name") or c["id"]),
              "type": str(c.get("type") or "relay")}
             for c in (info.get("channels") or []) if isinstance(c, dict) and c.get("id")]
    with _lock:
        _devices[did] = {
            "id": did,
            "name": str(name or info.get("name") or did),
            "alias": str(name or ""),
            "host": host,
            "port": port,
            "key": str(key or ""),
            "model": str(info.get("model") or ""),
            "fw": str(info.get("fw") or ""),
            "caps": [str(x) for x in (info.get("caps") or ["relay"])],
            "channels": chans,
            "ip": host,
            "source": "manual",
            "added_at": int(time.time()),
            "last_seen": int(time.time()),
        }
    _save()
    _probe_cache.pop(did, None)
    return dict(_devices[did])


def forget(did: str) -> bool:
    with _lock:
        gone = _devices.pop(str(did or ""), None)
    if gone:
        _save()
        _probe_cache.pop(str(did), None)
    return bool(gone)


def rename(did: str, name: str) -> dict:
    name = str(name or "").strip()[:40]
    with _lock:
        dev = _devices.get(str(did or ""))
        if not dev:
            raise EspError("没有这台设备", 404)
        dev["alias"] = name
        if name:
            dev["name"] = name
    _save()
    return dict(_devices[str(did)])


def state(did: str) -> dict:
    dev = resolve(did)
    if not dev:
        raise EspError("没有这台设备", 404)
    data = _req(dev, "/api/state", timeout=2.5)
    with _lock:
        if dev["id"] in _devices:
            _devices[dev["id"]]["last_seen"] = int(time.time())
            if isinstance(data.get("channels"), dict):
                # 设备自己报的通道表最准（可能刚改过固件）
                chans = _devices[dev["id"]].get("channels") or []
                known = {c["id"] for c in chans}
                for cid, cv in data["channels"].items():
                    if cid not in known and isinstance(cv, dict):
                        chans.append({"id": str(cid), "name": str(cv.get("name") or cid),
                                      "type": str(cv.get("type") or "relay")})
                _devices[dev["id"]]["channels"] = chans
    return data


def control(did: str, channel: str = "", on=None, toggle: bool = False,
            action: str = "", extra: dict | None = None) -> dict:
    dev = resolve(did)
    if not dev:
        raise EspError("没有这台设备", 404)
    body: dict = {}
    if action:
        body["action"] = str(action)
    if channel:
        body["channel"] = str(channel)
    if on is not None:
        if isinstance(on, str):
            on = on.strip().lower() in ("1", "true", "on", "yes", "开", "打开", "开灯")
        body["on"] = bool(on)
    if toggle:
        body["toggle"] = True
    if not body:
        raise EspError("没说做什么：给 channel+on，或者 action")
    if extra:
        for k, v in extra.items():
            if k not in body and isinstance(k, str) and k.isidentifier():
                body[k] = v
    data = _req(dev, "/api/cmd", body, timeout=3.0)
    _probe_cache[dev["id"]] = (time.time(), True)
    with _lock:
        if dev["id"] in _devices:
            _devices[dev["id"]]["last_seen"] = int(time.time())
    return data
