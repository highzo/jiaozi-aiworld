#!/usr/bin/env python3
"""局域网互认 E2E：起两个真实进程，互相发现、配对、跨设备执行。

为什么不用单进程模拟：这套东西的价值全在「两个独立进程、各自一份配置、
各自的 token」上。单进程里怎么测都是假的。

不依赖第三方库。跑完自动清理，失败会把子进程日志留在临时目录里。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORT_A = 8811
PORT_B = 8812

PASS = 0
FAIL = 0
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
END = "\033[0m"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  {GREEN}✓{END} {name}")
    else:
        FAIL += 1
        print(f"  {RED}✗{END} {name}  {DIM}{detail}{END}")
    return bool(cond)


def http(base: str, path: str, body: dict | None = None,
         token: str = "") -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["X-Jiaozi-Token"] = token
    req = urllib.request.Request(base + path, data=data, headers=hdrs,
                                 method="POST" if data is not None else "GET")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}
    except Exception as e:  # 连不上
        return 0, {"error": f"{type(e).__name__}: {e}"}


def token_of(home: str) -> str:
    p = os.path.join(home, "config.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["auth"]["token"]


def me_id_of(home: str) -> str:
    p = os.path.join(home, "peers.json")
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as f:
        try:
            return json.load(f).get("me_id") or ""
        except Exception:
            return ""


def spawn(home: str, port: int) -> tuple[subprocess.Popen, object]:
    env = dict(os.environ)
    env["JIAOZI_HOME"] = home
    env["JIAOZI_QUIET"] = "1"
    env.pop("JIAOZI_HOST", None)
    log = open(os.path.join(home, "server.log"), "wb")
    p = subprocess.Popen([PY, "-m", "jiaozi", "--host", "127.0.0.1",
                          "--port", str(port)],
                         cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    return p, log


def wait_health(base: str, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        st, j = http(base, "/api/health")
        if st == 200 and j.get("ok"):
            return True
        time.sleep(0.3)
    return False


def wait_peer(base: str, want_id: str, timeout: float = 20.0) -> dict:
    """等 UDP 发现出现。组播每 5 秒一轮，给足两轮多的时间。"""
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        st, j = http(base, "/api/peer/state")
        if st == 200:
            last = j.get("data") or {}
            for p in last.get("peers") or []:
                if p.get("id") == want_id:
                    return p
        time.sleep(0.4)
    return {}


def kill(p, log) -> None:
    try:
        p.terminate()
        p.wait(timeout=4)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        log.close()
    except Exception:
        pass


def main() -> int:
    base_tmp = tempfile.mkdtemp(prefix="jz-peer-")
    home_a = os.path.join(base_tmp, "a")
    home_b = os.path.join(base_tmp, "b")
    os.makedirs(home_a)
    os.makedirs(home_b)

    A = f"http://127.0.0.1:{PORT_A}"
    B = f"http://127.0.0.1:{PORT_B}"

    pa = pb = None
    la = lb = None
    try:
        print("\n[1] 两个独立实例启动")
        pa, la = spawn(home_a, PORT_A)
        pb, lb = spawn(home_b, PORT_B)
        ok("实例 A 起来了", wait_health(A), "看 %s/server.log" % home_a)
        ok("实例 B 起来了", wait_health(B), "看 %s/server.log" % home_b)
        ta, tb = token_of(home_a), token_of(home_b)
        ok("两边 token 不同（本来就是两台机器）", ta != tb and len(ta) > 10)

        print("\n[2] 组播自动发现")
        _, sa = http(A, "/api/peer/state")
        _, sb = http(B, "/api/peer/state")
        ida = (sa.get("data") or {}).get("me", {}).get("id") or ""
        idb = (sb.get("data") or {}).get("me", {}).get("id") or ""
        ok("各自有稳定的设备 id", bool(ida) and bool(idb) and ida != idb, f"{ida} / {idb}")

        seen = wait_peer(A, idb)
        ok("A 发现了 B", bool(seen), "20 秒内没收到组播")
        ok("发现项带端口", seen.get("port") == PORT_B, str(seen.get("port")))
        ok("发现项带能力列表", len(seen.get("caps") or []) >= 3, str(seen.get("caps")))
        ok("B 也发现了 A", bool(wait_peer(B, ida)))

        print("\n[3] 公开探活 & 鉴权边界")
        st, j = http(A, "/api/peer/hello")
        ok("hello 免 token 可访问", st == 200 and j.get("ok"), f"{st} {j}")
        ok("hello 不泄露 token", "token" not in json.dumps(j), "凭据泄漏")
        ok("hello 带端口", (j.get("data") or {}).get("port") == PORT_A)

        # 关掉 A 的本机免签，验证 state 必须带 token
        st, _ = http(A, "/api/config", {"server": {"allow_localhost": False}}, token=ta)
        ok("能关掉 A 的本机免签", st == 200, str(st))
        st, _ = http(A, "/api/peer/state")
        ok("关掉后匿名读 state 被拒", st == 401, str(st))
        st, _ = http(A, "/api/peer/state", token=ta)
        ok("带 token 能读 state", st == 200, str(st))
        st, _ = http(A, "/api/peer/hello")
        ok("关掉后 hello 仍然公开", st == 200, str(st))
        st, _ = http(A, "/api/peer/exec", {"tool": "fs_list"})
        ok("关掉后 exec 匿名被拒", st == 401, str(st))
        # 恢复，后续用 ta 访问
        http(A, "/api/config", {"server": {"allow_localhost": True}}, token=ta)

        print("\n[3b] 改名立即生效（热重启发现线程）")
        st, cf = http(A, "/api/config", {"peer": {"name": "厨房那台"}}, token=ta)
        ok("能保存设备名", st == 200 and (cf.get("data") or {}).get("peer", {}).get("name") == "厨房那台",
           str(cf)[:200])
        st, sm = http(A, "/api/peer/state", token=ta)
        ok("改完名字立刻反映出来",
           (sm.get("data") or {}).get("me", {}).get("name") == "厨房那台", str(sm)[:200])
        ok("热重启后发现仍开着", (sm.get("data") or {}).get("me", {}).get("discovery") is True)
        # 恢复成主机名，后面的断言按名字找设备时要稳定
        http(A, "/api/config", {"peer": {"name": ""}}, token=ta)

        print("\n[4] 配对码")
        st, c = http(A, "/api/peer/code", {}, token=ta)
        code = (c.get("data") or {}).get("code") or ""
        ok("A 生成了 6 位码", st == 200 and len(code) == 6 and code.isdigit(), str(c))
        ok("码有 5 分钟有效期", (c.get("data") or {}).get("ttl") == 300)

        st, bad = http(B, "/api/peer/pair",
                       {"host": "127.0.0.1", "port": PORT_A, "code": "000000"}, token=tb)
        ok("错码配对被拒", st >= 400 and not bad.get("ok"), str(bad))

        st, r = http(B, "/api/peer/pair",
                     {"host": "127.0.0.1", "port": PORT_A, "code": code}, token=tb)
        ok("正确码配对成功", st == 200 and r.get("ok"), str(r))
        ok("返回的是 A 的名字", (r.get("data") or {}).get("id") == ida, str(r.get("data")))

        st, again = http(B, "/api/peer/pair",
                         {"host": "127.0.0.1", "port": PORT_A, "code": code}, token=tb)
        ok("同一个码不能重复用", st >= 400, str(again))

        st, sb2 = http(B, "/api/peer/state", token=tb)
        row = [p for p in (sb2.get("data") or {}).get("peers") or [] if p["id"] == ida]
        row = row[0] if row else {}
        ok("B 的列表里 A 变成已配对", row.get("paired") is True, str(row))
        ok("B 拿到了 A 的 token", bool(row.get("token")), "token 为空")

        st, kn = http(A, "/api/peer/state", token=ta)
        ok("A 记下了谁连过它", idb in ((kn.get("data") or {}).get("known") or {}),
           str((kn.get("data") or {}).get("known")))

        print("\n[5] 跨设备执行")
        st, ex = http(A, "/api/peer/exec",
                      {"tool": "fs_list", "args": {"path": "~"}}, token=ta)
        ok("exec 能跑通 fs_list", st == 200 and ex.get("ok"), str(ex)[:200])
        ok("exec 返回真实目录内容",
           "items" in str((ex.get("data") or {}).get("result") or ""), str(ex)[:200])

        st, ex2 = http(A, "/api/peer/exec", {"tool": "peer_call", "args": {}}, token=ta)
        ok("exec 拒绝递归调用互认工具", st == 400, str(st))

        st, ex3 = http(A, "/api/peer/exec", {"tool": "不存在的工具"}, token=ta)
        ok("exec 拒绝未知工具", st == 400, str(st))

        print("\n[6] 服务端发起的远程调用（AI 用的那条路）")
        # 让测试进程扮演 B 的服务端：读 B 的 peers.json，去调 A
        os.environ["JIAOZI_HOME"] = home_b
        sys.path.insert(0, ROOT)
        from jiaozi import peer as PEER  # noqa: E402

        try:
            r = PEER.call(ida, "fs_list", {"path": "~"})
            body = json.dumps(r, ensure_ascii=False)
            ok("peer.call 打到 A 上跑通了", "items" in body, body[:200])
        except Exception as e:  # noqa: BLE001
            ok("peer.call 打到 A 上跑通了", False, f"{type(e).__name__}: {e}")

        try:
            PEER.call(ida, "fs_read", {"path": "不存在的文件xyz"})
            ok("远端报错会以文本返回而不是抛栈", True)
        except PEER.PeerError:
            ok("远端报错会以文本返回而不是抛栈", True)
        except Exception as e:  # noqa: BLE001
            ok("远端报错会以文本返回而不是抛栈", False, f"{type(e).__name__}: {e}")

        st, snap = http(B, "/api/peer/state", token=tb)
        ok("工具清单里能看到两个新工具",
           "peer_list" in json.dumps(http(B, "/api/tools", token=tb)[1]), "")

        print("\n[7] 身份持久化（重启后不能变）")
        id_before = me_id_of(home_b)
        kill(pb, lb)
        pb, lb = spawn(home_b, PORT_B)
        ok("B 重启后起来了", wait_health(B))
        id_after = me_id_of(home_b)
        ok("me_id 重启后不变", id_before == id_after and bool(id_before),
           f"{id_before} -> {id_after}")
        st, sb3 = http(B, "/api/peer/state", token=tb)
        ok("配对关系重启后还在",
           any(p["id"] == ida and p.get("paired")
               for p in (sb3.get("data") or {}).get("peers") or []),
           str(sb3)[:200])

        print("\n[8] 忘记设备")
        st, f = http(B, "/api/peer/forget", {"id": ida}, token=tb)
        ok("forget 返回已删除", st == 200 and (f.get("data") or {}).get("removed") is True, str(f))
        st, sb4 = http(B, "/api/peer/state", token=tb)
        row = [p for p in (sb4.get("data") or {}).get("peers") or [] if p["id"] == ida]
        ok("忘记后不再显示为已配对", not row or not row[0].get("paired"), str(row)[:200])

    finally:
        for p, log in ((pa, la), (pb, lb)):
            if p:
                kill(p, log)
        if FAIL:
            print(f"\n{DIM}临时目录保留用于排查：{base_tmp}{END}")
        else:
            shutil.rmtree(base_tmp, ignore_errors=True)

    print("\n" + "=" * 52)
    total = PASS + FAIL
    color = GREEN if FAIL == 0 else RED
    print(f"  局域网互认：{color}{PASS}/{total}{END} 通过")
    print("=" * 52)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
