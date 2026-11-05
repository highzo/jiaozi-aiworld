"""局域网互认：让同一个网络里的饺子互相看得见、连得上。

只有三件事，每件都很薄：

1. **发现** —— UDP 组播，每 5 秒报一次身份（id / 名字 / 端口 / 能力）。
2. **配对** —— 一台显示 6 位码，另一台输入，换到对方的访问 token。
3. **调用** —— 拿到 token 之后走的就是普通 ``/api/*``，不发明新协议。

为什么不用 mDNS：标准库没有 Zeroconf，而它是第三方包。组播 UDP 一百行就够，
安卓 Termux、开发板、Windows 三边都能跑起来，不需要装任何东西。

设计上刻意留了「手动添加」这条路。很多办公室/公共 WiFi 会禁组播，
*发现不了不等于连不上*——输入 IP + 配对码一样能通，只是要人手填一次。
"""
from __future__ import annotations

import json
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import config

#: 私网组播地址，和 mDNS 的 224.0.0.251 错开，避免抢包
GROUP = "239.255.77.87"
UDP_PORT = 8788
ANNOUNCE_EVERY = 5.0
PEER_TTL = 18.0
CODE_TTL = 300
CODE_MAX_TRIES = 6


class PeerError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.msg = msg
        self.code = code


_lock = threading.RLock()
_seen: dict[str, dict] = {}
_codes: dict[str, dict] = {}
_sock: socket.socket | None = None
_tx: socket.socket | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_port = 8787
_udp = UDP_PORT
_ok = False
_err = ""


# ------------------------------------------------------------------ 身份

def _path():
    return config.DATA_DIR / "peers.json"


def _write(raw: dict) -> None:
    try:
        p = _path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(p)
    except OSError as e:  # 磁盘只读 / 安卓沙箱受限：不能因为存档失败就崩掉整个服务
        print(f"[peer] 写入 {_path()} 失败：{e}")


def _state() -> dict:
    """读取本机身份与已配对表；首次调用时生成持久化的 me_id。

    必须持久化：id 一变，所有已配对关系全部失效，用户得重新配对一遍。
    """
    with _lock:
        raw = None
        p = _path()
        if p.exists():
            try:
                raw = json.loads(p.read_text("utf-8"))
            except Exception:
                raw = None
        if not isinstance(raw, dict):
            raw = {}
        changed = False
        if not raw.get("me_id"):
            raw["me_id"] = uuid.uuid4().hex[:12]
            changed = True
        for k in ("paired", "known"):
            if not isinstance(raw.get(k), dict):
                raw[k] = {}
                changed = True
        if changed:
            _write(raw)
        return raw


def my_id() -> str:
    return str(_state()["me_id"])


def my_name() -> str:
    cfg = config.load()
    n = str((cfg.get("peer") or {}).get("name") or "").strip()
    return n or socket.gethostname() or "未命名设备"


def caps() -> list[str]:
    cfg = config.load()
    out = ["fs", "term", "ui", "agent"]
    if cfg["image"].get("enabled"):
        out.append("image")
    if cfg["device"].get("enabled"):
        out.append("device")
    return out


def _platform() -> str:
    if os.name == "nt":
        return "windows"
    if "com.termux" in (os.environ.get("PREFIX") or ""):
        return "android"
    return "linux"


def local_ips() -> list[str]:
    """本机所有对外的 IPv4。用于显示，也用于逐个网卡发组播。"""
    out: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # 不真的发包，只为拿到出口地址
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
    except OSError:
        pass
    return [ip for ip in out
            if ip and not ip.startswith("127.") and not ip.startswith("169.254.")]


def _primary_ip() -> str:
    ips = local_ips()
    return ips[0] if ips else ""


def hello() -> dict:
    """公开信息：给还拿不到 token 的对端做探活，不含任何凭据。"""
    return {"id": my_id(), "name": my_name(), "port": _port,
            "ver": config.VERSION, "plat": _platform(), "caps": caps(),
            "ips": local_ips()}


# ------------------------------------------------------------------ 发现

def _payload() -> bytes:
    d = {"jz": 1, "id": my_id(), "name": my_name(), "port": _port,
         "ver": config.VERSION, "plat": _platform(), "caps": caps()}
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


def announce() -> None:
    """往每张网卡各发一遍。多网卡（WSL/Hyper-V/VMware 虚拟网卡）时只发默认网卡会漏。"""
    if not _ok or _tx is None:
        return
    data = _payload()
    ips = local_ips()
    if not ips:
        ips = [""]
    for ip in ips:
        if ip:
            try:
                _tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                               socket.inet_aton(ip))
            except OSError:
                continue
        try:
            _tx.sendto(data, (GROUP, _udp))
        except OSError:
            pass


def _listen() -> None:
    # 拿局部引用：stop() 会关掉 socket，用全局变量可能在关闭后拿到 None
    s = _sock
    while not _stop.is_set():
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break  # socket 已被关闭，线程退出
        try:
            d = json.loads(data.decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("jz") != 1:
            continue
        pid = str(d.get("id") or "")
        if not pid or pid == my_id():
            continue  # 自己发的，忽略
        try:
            port = int(d.get("port") or 8787)
        except (TypeError, ValueError):
            port = 8787
        with _lock:
            _seen[pid] = {
                "id": pid,
                "name": d.get("name") or pid,
                "ip": addr[0],
                "port": port,
                "ver": d.get("ver") or "",
                "plat": d.get("plat") or "",
                "caps": d.get("caps") or [],
                "ts": time.time(),
            }


def _announce_loop() -> None:
    announce()
    while not _stop.wait(ANNOUNCE_EVERY):
        announce()


def start(port: int) -> bool:
    """启动发现。失败不抛异常 —— 发现是增强功能，不能拖垮整个服务。"""
    global _sock, _tx, _thread, _port, _udp, _ok, _err
    cfg = config.load()
    _port = int(port or 8787)
    peer_cfg = cfg.get("peer") or {}
    if not peer_cfg.get("discovery", True):
        _err = "发现已关闭"
        return False
    if not peer_cfg.get("enabled", True):
        _err = "互认已关闭"
        return False
    try:
        _udp = int(peer_cfg.get("udp_port") or UDP_PORT)
    except (TypeError, ValueError):
        _udp = UDP_PORT
    _stop.clear()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 同一台机器跑两个实例（测试常见）要都能收到，Linux 需要 REUSEPORT
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.settimeout(1.0)
        s.bind(("", _udp))
        # ip_mreq 就是两个 4 字节地址，直接拼字节，省掉 struct 格式的平台差异
        mreq = socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0")
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except OSError as e:
        _ok = False
        _err = f"{type(e).__name__}: {e}"
        print(f"[peer] 局域网发现未启动（{_err}）。手动配对仍然可用。")
        return False

    _sock, _tx, _ok, _err = s, t, True, ""
    _thread = threading.Thread(target=_listen, name="jiaozi-peer-rx", daemon=True)
    _thread.start()
    threading.Thread(target=_announce_loop, name="jiaozi-peer-tx", daemon=True).start()
    return True


def stop() -> None:
    """停发现并关 socket。关掉而不是只置标志，是为了能立刻原地重启
    （用户在设置里改名/开关发现时走这条路，不该逼人重启整个服务）。"""
    global _ok, _sock, _tx
    _stop.set()
    _ok = False
    for s in (_sock, _tx):
        try:
            if s is not None:
                s.close()
        except OSError:
            pass
    _sock = None
    _tx = None


# ------------------------------------------------------------------ 配对

def make_code() -> dict:
    """生成一次性 6 位码。给「在另一台机器上输入」用。"""
    code = f"{random.randint(0, 999999):06d}"
    exp = time.time() + CODE_TTL
    now = time.time()
    with _lock:
        for k in [k for k, v in _codes.items() if v["exp"] < now]:
            _codes.pop(k, None)
        _codes[code] = {"exp": exp, "tries": 0}
    return {"code": code, "expires": exp, "ttl": CODE_TTL, "name": my_name()}


def claim(code: str, peer: dict) -> dict:
    """对端拿码来换 token。

    这是**唯一一个不需要鉴权的写接口**，安全性全靠：一次性 + 5 分钟过期 + 试错上限。
    码只能从本机界面上看到，所以等价于「人在这台机器旁边点了一下同意」。
    """
    code = (code or "").strip()
    now = time.time()
    with _lock:
        rec = _codes.get(code)
        if not rec:
            raise PeerError("配对码不正确，或已经用过了")
        if rec["exp"] < now:
            _codes.pop(code, None)
            raise PeerError("配对码已过期，请重新生成")
        rec["tries"] += 1
        if rec["tries"] > CODE_MAX_TRIES:
            _codes.pop(code, None)
            raise PeerError("试错次数过多，配对码已作废")
        _codes.pop(code, None)  # 一次性

    cfg = config.load()
    pid = str(peer.get("id") or "")
    if pid and pid != my_id():
        st = _state()
        # known 只是「谁连过我」，不带凭据，纯展示用
        st["known"][pid] = {
            "id": pid,
            "name": peer.get("name") or pid,
            "host": peer.get("ip") or "",
            "port": int(peer.get("port") or 0),
            "ts": now,
        }
        _write(st)
    return {"token": cfg["auth"]["token"], "id": my_id(), "name": my_name(),
            "port": _port, "ver": config.VERSION}


def _post(host: str, port: int, path: str, body: dict,
          timeout: float = 8.0, token: str = "") -> dict:
    url = f"http://{host}:{port}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        hdrs["X-Jiaozi-Token"] = token
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    # 局域网直连，必须绕开系统代理，否则开了代理的机器会 502
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        msg = raw[:300]
        try:
            msg = json.loads(raw).get("error") or msg
        except Exception:
            pass
        raise PeerError(msg or f"对方返回 {e.code}", e.code) from e
    except urllib.error.URLError as e:
        raise PeerError(f"连不上 {host}:{port}（{e.reason}）") from e
    except (socket.timeout, TimeoutError) as e:
        raise PeerError(f"{host}:{port} 响应超时") from e


def _get(host: str, port: int, path: str, timeout: float = 4.0) -> dict:
    url = f"http://{host}:{port}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise PeerError(f"对方返回 {e.code}", e.code) from e
    except urllib.error.URLError as e:
        raise PeerError(f"连不上 {host}:{port}（{e.reason}）") from e
    except (socket.timeout, TimeoutError) as e:
        raise PeerError(f"{host}:{port} 响应超时") from e


def probe(host: str, port: int) -> dict:
    host = (host or "").strip()
    try:
        port = int(port or 8787)
    except (TypeError, ValueError):
        port = 8787
    if not host:
        raise PeerError("填一下设备地址")
    res = _get(host, port, "/api/peer/hello")
    if not res.get("ok"):
        raise PeerError(res.get("error") or "对方不是饺子")
    data = res.get("data") or {}
    return {"host": host, "port": port, **data}


def pair(host: str, port: int, code: str) -> dict:
    """本机作为「申请方」：拿对方的码，换对方的 token 并永久保存。"""
    host = (host or "").strip()
    code = (code or "").strip()
    try:
        port = int(port or 0)
    except (TypeError, ValueError):
        port = 0
    if not host:
        raise PeerError("填一下对方设备的地址")
    if port <= 0:
        port = 8787
    if not code:
        raise PeerError("填一下对方屏幕上显示的 6 位配对码")

    res = _post(host, port, "/api/peer/claim", {
        "code": code, "id": my_id(), "name": my_name(),
        "port": _port, "ip": _primary_ip(),
    })
    data = res.get("data") or {}
    token = str(data.get("token") or "")
    pid = str(data.get("id") or "")
    if not res.get("ok") or not token or not pid:
        raise PeerError(res.get("error") or "对方没有返回凭据，可能版本不匹配")
    if pid == my_id():
        raise PeerError("这是本机自己")

    st = _state()
    st["paired"][pid] = {
        "id": pid,
        "name": data.get("name") or pid,
        "host": host,
        "port": int(data.get("port") or port),
        "token": token,
        "paired_at": time.time(),
    }
    _write(st)
    return {"id": pid, "name": st["paired"][pid]["name"],
            "host": host, "port": st["paired"][pid]["port"]}


def forget(pid: str) -> dict:
    st = _state()
    had = st["paired"].pop(pid, None) is not None
    _write(st)
    return {"removed": had, "id": pid}


# ------------------------------------------------------------------ 调用

def _addr_of(pid: str) -> tuple[str, int, str]:
    st = _state()
    p = st["paired"].get(pid)
    if not p:
        raise PeerError("这个设备还没配对")
    live = _seen.get(pid) or {}
    # DHCP 会换 IP：发现到的地址比配对时记下的更新，优先用
    host = live.get("ip") or p.get("host") or ""
    port = int(live.get("port") or p.get("port") or 8787)
    if not host:
        raise PeerError("不知道这个设备现在在哪，先让它在线")
    return host, port, str(p.get("token") or "")


def call(pid: str, tool: str, args: dict, timeout: float = 90.0) -> dict:
    """在另一台设备上执行一个工具。这是「隔空操控电脑」的唯一入口。"""
    host, port, token = _addr_of(pid)
    res = _post(host, port, "/api/peer/exec",
                {"tool": tool, "args": args or {}}, timeout=timeout, token=token)
    if not res.get("ok"):
        raise PeerError(res.get("error") or "远端执行失败")
    return res.get("data") or {}


# ------------------------------------------------------------------ 快照

def snapshot() -> dict:
    st = _state()
    now = time.time()
    paired = st.get("paired") or {}
    out: list[dict] = []
    taken: set[str] = set()

    for pid, v in paired.items():
        live = _seen.get(pid) or {}
        online = bool(live) and (now - float(live.get("ts") or 0) < PEER_TTL)
        out.append({
            "id": pid,
            "name": v.get("name") or pid,
            "host": v.get("host") or "",
            "port": int(v.get("port") or 0),
            "ip": live.get("ip") or v.get("host") or "",
            "caps": live.get("caps") or [],
            "plat": live.get("plat") or "",
            "paired": True,
            "online": online,
            "seen_at": float(live.get("ts") or 0),
            # 对方的访问凭据。前端拿它拼「打开对方桌面」的地址。
            # 能读这个接口的调用方本来就已经通过本机鉴权（或在本机回环），
            # 而本机回环等价于全权，所以这里不额外做一层遮罩。
            "token": str(v.get("token") or ""),
        })
        taken.add(pid)

    for pid, s in list(_seen.items()):
        if pid in taken or now - float(s.get("ts") or 0) > PEER_TTL:
            continue
        out.append({
            "id": pid, "name": s.get("name") or pid,
            "host": s.get("ip") or "", "port": int(s.get("port") or 0),
            "ip": s.get("ip") or "", "caps": s.get("caps") or [],
            "plat": s.get("plat") or "", "paired": False, "online": True,
            "seen_at": float(s.get("ts") or 0),
        })

    out.sort(key=lambda x: (not x["online"], not x["paired"], x["name"] or ""))

    return {
        "me": {"id": my_id(), "name": my_name(), "port": _port,
               "ips": local_ips(), "discovery": _ok, "error": _err,
               "plat": _platform()},
        "peers": out,
        "known": st.get("known") or {},
        "now": now,
    }


def peer_name(pid: str) -> str:
    st = _state()
    p = st["paired"].get(pid) or {}
    return str(p.get("name") or pid)
