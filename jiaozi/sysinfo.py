"""系统信息采集，尽量用标准库。目标平台是 Linux/Android/ARM，Windows 走降级实现。"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time

from . import config

_PREV = {"idle": 0, "total": 0, "t": 0.0}


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def cpu_percent() -> float:
    if os.path.exists("/proc/stat"):
        line = _read("/proc/stat").split("\n", 1)[0]
        parts = [int(x) for x in line.split()[1:] if x.isdigit()]
        if len(parts) >= 4:
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            total = sum(parts)
            di = idle - _PREV["idle"]
            dt = total - _PREV["total"]
            _PREV.update(idle=idle, total=total)
            if dt <= 0:
                return 0.0
            return round(max(0.0, min(100.0, 100.0 * (1 - di / dt))), 1)
    return _win_cpu()


def _win_cpu() -> float:
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]

        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        k32 = ctypes.windll.kernel32
        k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))

        def ft(f):
            return (f.dwHighDateTime << 32) | f.dwLowDateTime

        now = (ft(idle), ft(kern), ft(user))
        prev = _PREV.get("win")
        _PREV["win"] = now
        if not prev:
            return 0.0
        di = now[0] - prev[0]
        dt = (now[1] - prev[1]) + (now[2] - prev[2])
        if dt <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * (1 - di / dt))), 1)
    except Exception:
        return 0.0


def memory() -> dict:
    txt = _read("/proc/meminfo")
    if txt:
        kv = {}
        for line in txt.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = int(v.split()[0]) * 1024 if v.split() else 0
        total = kv.get("MemTotal", 0)
        avail = kv.get("MemAvailable", kv.get("MemFree", 0))
        swap_total = kv.get("SwapTotal", 0)
        swap_free = kv.get("SwapFree", 0)
        return {"total": total, "used": max(0, total - avail), "free": avail,
                "percent": round(100 * (total - avail) / total, 1) if total else 0,
                "swap_total": swap_total, "swap_used": max(0, swap_total - swap_free)}
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        total, avail = m.ullTotalPhys, m.ullAvailPhys
        return {"total": total, "used": total - avail, "free": avail,
                "percent": round(m.dwMemoryLoad, 1), "swap_total": m.ullTotalPageFile,
                "swap_used": m.ullTotalPageFile - m.ullAvailPageFile}
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "percent": 0,
                "swap_total": 0, "swap_used": 0}


def uptime() -> float:
    txt = _read("/proc/uptime")
    if txt:
        try:
            return float(txt.split()[0])
        except ValueError:
            pass
    try:
        import ctypes
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        return 0.0


def load_avg() -> list[float]:
    try:
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return [0.0, 0.0, 0.0]


def processes(limit: int = 60, sort: str = "cpu") -> list[dict]:
    if os.path.isdir("/proc"):
        return _proc_linux(limit)
    return _proc_windows(limit)


def _proc_linux(limit: int) -> list[dict]:
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    try:
        hz = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        hz = 100
    total_mem = memory().get("total") or 1
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        stat = _read(f"/proc/{pid}/stat")
        if not stat:
            continue
        try:
            rp = stat.rfind(")")
            name = stat[stat.find("(") + 1:rp]
            rest = stat[rp + 2:].split()
            state = rest[0]
            utime, stime = int(rest[11]), int(rest[12])
            rss = int(rest[21]) * page
            out.append({"pid": int(pid), "name": name, "state": state,
                        "cpu_time": round((utime + stime) / hz, 2),
                        "rss": rss,
                        "mem_percent": round(100 * rss / total_mem, 2)})
        except (IndexError, ValueError):
            continue
    out.sort(key=lambda x: x["rss"], reverse=True)
    return out[:limit]


def _proc_windows(limit: int) -> list[dict]:
    try:
        res = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=8,
                             creationflags=0x08000000)
        text = res.stdout.decode("utf-8", "replace") or res.stdout.decode("gbk", "replace")
        out = []
        for line in text.splitlines():
            cols = [c.strip('"') for c in line.split('","')]
            if len(cols) < 5:
                continue
            name = cols[0].lstrip('"')
            try:
                pid = int(cols[1].replace(",", ""))
                mem = int(cols[4].replace(",", "").replace(" K", "").replace("K", "")) * 1024
            except ValueError:
                continue
            out.append({"pid": pid, "name": name, "state": "R",
                        "cpu_time": 0, "rss": mem, "mem_percent": 0})
        out.sort(key=lambda x: x["rss"], reverse=True)
        return out[:limit]
    except Exception:
        return []


def kill(pid: int, force: bool = False) -> dict:
    if pid <= 1:
        raise ValueError("拒绝操作该进程")
    try:
        if os.name == "posix":
            os.kill(pid, 9 if force else 15)
        else:
            subprocess.run(["taskkill", "/F" if force else "", "/PID", str(pid)],
                           capture_output=True, timeout=5,
                           creationflags=0x08000000)
        return {"pid": pid, "killed": True}
    except Exception as e:
        return {"pid": pid, "killed": False, "error": str(e)}


def info() -> dict:
    cfg = config.load()
    roots = config.sandbox_roots(cfg)
    disk = shutil.disk_usage(str(roots[0]))
    from . import fsapi
    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
        "cpu_percent": cpu_percent(),
        "load": load_avg(),
        "memory": memory(),
        "uptime": round(uptime(), 1),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free,
                 "percent": round(100 * disk.used / disk.total, 1) if disk.total else 0},
        "root": str(roots[0]),
        "roots": fsapi.roots_view(),
        "app": {"version": cfg["_meta"] if "_meta" in cfg else None},
        "clients": None,
    }
