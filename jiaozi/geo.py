"""饺子AIWorld · IP 地理位置 → 首次启动语言

设计约束（每一条都来自真机踩坑）：

1. **断网不能卡界面。** 这是桌面系统，不是网页。任何一次 3 秒超时卡在启动路径上，
   用户看到的就是"打不开"。所以这里超时 3 秒、失败即返回、答案落盘缓存 6 小时，
   并且前端是**先渲染、后切换**，不是在白屏上等 IP 定位。
2. **内网地址定位不出国家。** 手机连局域网访问时，对端 IP 是 192.168.x.x。
   这时要定位**服务器自己的出口 IP**，否则永远匹配不到。
3. **多provider。** api.ip.sb 在某些网络下会 403/超时（实测无 UA 直接 403），
   所以依次回退，任何一个成功就停。
4. **不信任 provider 的字段名。** 三家字段名都不同（country_code / countryCode /
   country），这里统一成一套内部结构。
"""
from __future__ import annotations

import ipaddress
import json
import threading
import time
import urllib.request
from pathlib import Path

from . import config

#: 缓存有效期：6 小时。IP 归属地不会分钟级变化，避免每次开页面都打第三方接口。
TTL = 6 * 3600
#: 单次请求超时。宁可没有语言建议，也不能让界面等。
TIMEOUT = 3.0

_UA = "JiaoziAIWorld/%s (+https://github.com/)" % config.VERSION
_lock = threading.RLock()
_mem: dict = {"ts": 0.0, "data": None}
_CACHE_FILE = config.DATA_DIR / "geo.json"


def _is_private(ip: str) -> bool:
    """回环 / 内网 / 链路本地 / 保留地址 —— 这些都定位不出国家。"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (a.is_private or a.is_loopback or a.is_link_local
            or a.is_reserved or a.is_multicast or a.is_unspecified)


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read(64 * 1024)
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


def _from_ip_sb(ip: str) -> dict | None:
    """首选。返回字段最全（含 ASN、时区），实测国内网络最稳。"""
    d = _get("https://api.ip.sb/geoip/" + (ip or ""))
    if not d or not d.get("country_code"):
        return None
    return {
        "ip": d.get("ip") or ip,
        "country_code": str(d["country_code"]).upper(),
        "country": d.get("country") or "",
        "city": d.get("city") or "",
        "region": d.get("region") or "",
        "source": "ip.sb",
    }


def _from_ipwho(ip: str) -> dict | None:
    d = _get("https://ipwho.is/" + (ip or ""))
    if not d or not d.get("success") or not d.get("country_code"):
        return None
    return {
        "ip": d.get("ip") or ip,
        "country_code": str(d["country_code"]).upper(),
        "country": d.get("country") or "",
        "city": d.get("city") or "",
        "region": d.get("region") or "",
        "source": "ipwho.is",
    }


def _from_ipinfo(ip: str) -> dict | None:
    d = _get("https://ipinfo.io/%s/json" % (ip or ""))
    if not d or not d.get("country"):
        return None
    return {
        "ip": d.get("ip") or ip,
        "country_code": str(d["country"]).upper(),
        "country": d.get("country") or "",
        "city": d.get("city") or "",
        "region": d.get("region") or "",
        "source": "ipinfo.io",
    }


PROVIDERS = (_from_ip_sb, _from_ipwho, _from_ipinfo)


def _disk_read() -> dict | None:
    try:
        d = json.loads(_CACHE_FILE.read_text("utf-8"))
        if isinstance(d, dict) and d.get("data") and time.time() - float(d.get("ts") or 0) < TTL:
            return d
    except Exception:
        pass
    return None


def _disk_write(data: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def lookup(ip: str = "", force: bool = False) -> dict:
    """定位一个 IP；查不到就干净地返回 ok=False，绝不抛异常。

    ip 留空或传内网地址时，自动改为定位**本机出口 IP** —— 手机通过局域网
    访问桌面时，对端地址是 192.168.x.x，只有出口 IP 才带国家信息。
    """
    ip = (ip or "").strip()
    with _lock:
        if not force and _mem["data"] and time.time() - _mem["ts"] < TTL:
            return dict(_mem["data"], cached=True, ok=True)

    if not force:
        disk = _disk_read()
        if disk:
            data = disk["data"]
            if ip and not _is_private(ip) and data.get("ip") != ip:
                # 缓存的是出口 IP，但这次问的是另一个公网地址 → 重新查
                pass
            else:
                with _lock:
                    _mem["ts"] = float(disk["ts"])
                    _mem["data"] = data
                return dict(data, cached=True, ok=True)

    query_ip = "" if _is_private(ip) else ip
    last_err = ""
    deadline = time.time() + 4.5  # 三家串行最坏 9 秒，这里给总预算封顶
    for fn in PROVIDERS:
        if time.time() > deadline and last_err:
            break
        try:
            # 空字符串表示"让 provider 自己判断请求来源"，内部服务都支持
            data = fn(query_ip)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            continue
        if data:
            data["ts"] = time.time()
            data["auto"] = not query_ip  # 是否由出口 IP 推断
            with _lock:
                _mem["ts"] = data["ts"]
                _mem["data"] = data
            _disk_write(data)
            return dict(data, cached=False, ok=True)
        last_err = last_err or "所有 provider 都没返回国家码"

    return {"ok": False, "ip": ip, "error": last_err or "定位失败（可能离线）"}


def clear_cache() -> None:
    with _lock:
        _mem["ts"] = 0.0
        _mem["data"] = None
    try:
        Path(_CACHE_FILE).unlink()
    except Exception:
        pass
