#!/usr/bin/env python3
"""家电（ESP32）与语音的集成测试。

真起一个服务进程，再真起两三个「假 ESP32」（tools/esp_sim.py），
走和界面完全一样的 HTTP 接口。所以这里绿的，换成真板子只差一个 IP。

    python3 tests/devices_test.py

不需要硬件、不联网、不花钱。语音那部分用 mock 后端，只验证管道通不通，
不验证识别准不准——那是模型的事。
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = 0
FAIL = 0
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

for _k in ("no_proxy", "NO_PROXY"):
    os.environ[_k] = "127.0.0.1,localhost,::1"


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}" + (f"　{extra}" if extra else ""))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(base: str, method: str, path: str, body=None, token: str = "", timeout: float = 8.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with OPENER.open(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def wait_http(base: str, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        st, _ = req(base, "GET", "/api/health", timeout=1.5)
        if st == 200:
            return True
        time.sleep(0.3)
    return False


def make_wav(seconds: float = 1.2, rate: int = 16000, freq: float = 440.0) -> bytes:
    """造一段有声音的 WAV（16 位单声道）。给 mock 后端用，走真实解析路径。"""
    import math
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", v)
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVE"
           + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
           + b"data" + struct.pack("<I", len(frames)))
    return hdr + bytes(frames)


def main() -> int:
    home = tempfile.mkdtemp(prefix="jz-dev-")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, JIAOZI_HOME=home, JIAOZI_VOICE_MOCK="1",
               JIAOZI_VOICE_MOCK_TEXT="open the lamp")
    procs: list[subprocess.Popen] = []

    print("=" * 62)
    print("  家电 / 语音 集成测试")
    print("=" * 62)

    srv = subprocess.Popen(
        [sys.executable, "-u", "-m", "jiaozi", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    procs.append(srv)
    if not wait_http(base):
        print("服务没起来：")
        try:
            print((srv.stdout.read(4000) or b"").decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass
        return 1

    token = json.load(open(os.path.join(home, "config.json"), encoding="utf-8"))["auth"]["token"]
    say = lambda m, p, b=None, t=8.0: req(base, m, p, b, token, t)  # noqa: E731

    # ---------------------------------------------------------------- 启动模拟设备
    print("\n[1] 启动两台模拟 ESP32")
    sim1 = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tools", "esp_sim.py"),
         "--id", "esp32-a1b2", "--name", "客厅灯",
         "--channels", "r1:灯,r2:风扇", "--http-port", str(free_port()), "--no-listen"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    port2 = free_port()
    sim2 = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tools", "esp_sim.py"),
         "--id", "esp32-c3d4", "--name", "卧室空调",
         "--channels", "r1:空调", "--http-port", str(port2), "--key", "s3cret", "--no-listen"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    procs += [sim1, sim2]

    # ---------------------------------------------------------------- 发现
    print("\n[2] 自动发现（UDP 喊话）")
    found = []
    for _ in range(40):
        st, j = say("GET", "/api/esp/devices")
        found = (j.get("data") or {}).get("devices") or []
        if len(found) >= 2:
            break
        time.sleep(0.5)
    names = sorted(d["name"] for d in found)
    ok("发现两台设备", len(found) == 2, f"实际 {len(found)}: {names}")
    ok("名字正确", names == ["卧室空调", "客厅灯"], str(names))
    lamp = next((d for d in found if d["id"] == "esp32-a1b2"), {})
    ac = next((d for d in found if d["id"] == "esp32-c3d4"), {})
    ok("通道表带回来了", [c["id"] for c in lamp.get("channels") or []] == ["r1", "r2"])
    ok("在线状态为真", bool(lamp.get("online")) and bool(ac.get("online")))

    # ---------------------------------------------------------------- 开关
    print("\n[3] 开关（和界面点按钮走同一条路）")
    st, j = say("POST", "/api/esp/control", {"id": "esp32-a1b2", "channel": "r1", "on": True})
    ok("打开成功", st == 200 and (j.get("data") or {}).get("on") is True, str(j))
    st, j = say("GET", "/api/esp/state?id=esp32-a1b2")
    chans = (j.get("data") or {}).get("channels") or {}
    ok("状态读回来是开", (chans.get("r1") or {}).get("on") is True, str(chans))
    ok("另一路没被带着开", (chans.get("r2") or {}).get("on") is False)

    st, j = say("POST", "/api/esp/control", {"id": "esp32-a1b2", "channel": "r1", "toggle": True})
    ok("切换成关", (j.get("data") or {}).get("on") is False, str(j))

    st, j = say("POST", "/api/esp/control", {"id": "客厅灯", "channel": "r2", "on": True})
    ok("按名字也能定位到设备", st == 200 and (j.get("data") or {}).get("on") is True, str(j))

    st, j = say("POST", "/api/esp/control", {"id": "esp32-a1b2", "channel": "r9", "on": True})
    ok("不存在的通道报错而不是静默成功", st >= 400 and j.get("error"), f"{st} {j}")
    st, j = say("POST", "/api/esp/control", {"id": "esp32-a1b2"})
    ok("什么都不说时报错", st >= 400, f"{st} {j}")

    # ---------------------------------------------------------------- 密钥
    print("\n[4] 访问密钥")
    st, j = say("POST", "/api/esp/control", {"id": "esp32-c3d4", "channel": "r1", "on": True})
    ok("没密钥时被设备拒绝", st >= 400 and "401" in str(j.get("error") or ""), str(j))

    st, j = say("POST", "/api/esp/add", {"host": "127.0.0.1", "port": port2, "key": "s3cret"})
    ok("带密钥手动添加成功", st == 200 and (j.get("data") or {}).get("id") == "esp32-c3d4", str(j))
    st, j = say("POST", "/api/esp/control", {"id": "esp32-c3d4", "channel": "r1", "on": True})
    ok("加了密钥之后能开关", st == 200 and (j.get("data") or {}).get("on") is True, str(j))

    esp_json = os.path.join(home, "esp.json")
    raw = json.load(open(esp_json, encoding="utf-8")) if os.path.exists(esp_json) else {}
    ok("密钥随设备一起落盘", any(d.get("key") == "s3cret"
                                for d in (raw.get("devices") or {}).values()),
       str(list((raw.get("devices") or {}).keys())))

    st, j = say("POST", "/api/esp/add", {"host": "127.0.0.1", "port": port2, "key": "wrong"})
    ok("错误密钥添加失败并说明原因", st >= 400 and j.get("error"), f"{st} {j}")

    # ---------------------------------------------------------------- 离线
    print("\n[5] 设备离线时不装作成功")
    sim2.terminate()
    try:
        sim2.wait(5)
    except subprocess.TimeoutExpired:
        sim2.kill()
    sim2.terminate()
    time.sleep(7)  # 越过在线状态缓存
    st, j = say("POST", "/api/esp/control", {"id": "esp32-c3d4", "channel": "r1", "on": True})
    ok("离线设备报错", st >= 400 and j.get("error"), f"{st} {j}")
    st, j = say("GET", "/api/esp/devices")
    off = [d for d in (j.get("data") or {}).get("devices") or [] if d["id"] == "esp32-c3d4"]
    ok("列表里标成离线", off and off[0]["online"] is False, str(off))

    # ---------------------------------------------------------------- 改名 / 忘记
    print("\n[6] 改名与忘记")
    st, j = say("POST", "/api/esp/rename", {"id": "esp32-a1b2", "name": "客厅大灯"})
    ok("改名成功", (j.get("data") or {}).get("name") == "客厅大灯", str(j))
    st, j = say("POST", "/api/esp/forget", {"id": "esp32-c3d4"})
    ok("忘记成功", (j.get("data") or {}).get("forgot") is True, str(j))

    # ---------------------------------------------------------------- AI 工具
    print("\n[7] AI 也能开关（同一批设备）")
    code = (
        "import json,sys;"
        "from jiaozi.agent import tools;"
        "print(tools.dispatch('esp_devices', {}));"
        "print('---');"
        "print(tools.dispatch('esp_control', {'device':'客厅大灯','channel':'r1','on':True}))"
    )
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    out = (p.stdout or "") + (p.stderr or "")
    ok("esp_devices 能列出设备", "客厅大灯" in out, out[-300:])
    ok("esp_control 真的开了", '"on": true' in out.lower() or "'on': True" in out, out[-300:])

    code2 = ("from jiaozi.agent import tools;"
             "print(tools.dispatch('esp_control', {'device':'不存在的设备','on':True}))")
    p2 = subprocess.run([sys.executable, "-c", code2], cwd=ROOT, env=env,
                        capture_output=True, text=True, timeout=60)
    ok("AI 找不到设备时明确报错", "没有" in (p2.stdout or ""), (p2.stdout or "")[-200:])

    # ---------------------------------------------------------------- 语音
    print("\n[8] 语音管道")
    st, j = say("GET", "/api/voice/status")
    v = j.get("data") or {}
    ok("状态接口可用", st == 200 and v.get("backend") == "mock", str(j))
    ok("会告诉前端能不能用", "ready" in v and "hint" in v, str(v))

    import base64
    wav = make_wav(1.2)
    st, j = say("POST", "/api/voice/asr", {"wav": base64.b64encode(wav).decode()})
    d = j.get("data") or {}
    ok("识别返回文字", st == 200 and d.get("text") == "open the lamp", str(j))
    ok("带回了时长", (d.get("seconds") or 0) > 1.0, str(d))

    st, j = say("POST", "/api/voice/asr", {"wav": "not-base64!!"})
    ok("坏数据报错", st >= 400, f"{st} {j}")
    st, j = say("POST", "/api/voice/asr", {})
    ok("没音频报错", st >= 400, f"{st} {j}")

    st, j = say("POST", "/api/voice/asr",
                {"wav": base64.b64encode(b"RIFFxxxxWAVEjunk").decode()})
    ok("假 WAV 被挡住并说明原因", st >= 400 and j.get("error"), f"{st} {j}")

    # ---------------------------------------------------------------- 存档
    print("\n[9] 重启后设备还在")
    ok("注册表落盘了", os.path.exists(esp_json))
    if os.path.exists(esp_json):
        raw = json.load(open(esp_json, encoding="utf-8"))
        ids = list((raw.get("devices") or {}).keys())
        ok("改名后的设备还在存档里", "esp32-a1b2" in ids, str(ids))
        ok("被忘记的设备不在了", "esp32-c3d4" not in ids, str(ids))
        ok("存档带版本号", raw.get("version") == 1, str(raw.get("version")))

    # ---------------------------------------------------------------- 收尾
    for p in reversed(procs):
        try:
            p.terminate()
            p.wait(5)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    print("\n" + "=" * 62)
    print(f"  通过 {PASS}　失败 {FAIL}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
