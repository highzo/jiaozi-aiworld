#!/usr/bin/env python3
"""真模型 + 真浏览器的图像生成验收。

和 ui_test.py 的区别：这个脚本会花真钱、调真模型、等几十秒，
所以要单独跑，不进常规回归。

它验证的是产品最核心的那条链路：
  人在桌面里打一句话 → AI 自己决定调 image_gen → 图片落到磁盘
  → 对话里直接出现缩略图 → 点开能看大图

    python tests/image_e2e.py

环境变量：
    JIAOZI_URL   服务地址（默认 127.0.0.1:8787）
    JZ_PROMPT    要发给 AI 的话
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_test as U  # noqa: E402
from ui_test import WS, find_browser, ok, PASS, FAIL, reset_profile  # noqa: E402

URL = os.environ.get("JIAOZI_URL", "http://127.0.0.1:8787").rstrip("/") + "/"
PORT = int(os.environ.get("CDP_PORT", "9444"))
U.PORT = PORT  # wait_cdp 用的是模块级端口
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(SHOTS, exist_ok=True)

PROMPT = os.environ.get("JZ_PROMPT", "用 image_gen 画两张美女肖像：一张白衬衫窗边看书，一张秋天银杏树下。要真实照片质感。")


def main() -> int:
    exe = find_browser()
    if not exe:
        print("没有找到 Chrome/Edge，跳过")
        return 0

    # 先确认图像接口本身是通的，避免把配置问题误判成 UI 问题
    try:
        cfg = json.loads(urllib.request.urlopen(URL + "api/config", timeout=10).read())
        img = (cfg.get("data") or cfg).get("image") or {}
        print(f"图像模型: {img.get('model')}  接口: {img.get('base_url') or '(复用 llm)'}")
        ok("图像功能已启用", img.get("enabled") is not False)
    except Exception as e:
        print("读取配置失败:", e)
        return 1

    prof = os.path.join(tempfile.gettempdir(), "jz_cdp_img")
    reset_profile(prof)
    proc = subprocess.Popen([
        exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
        "--window-size=1440,900", "--hide-scrollbars", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ws = None
    try:
        ws = WS(U.wait_cdp(60)["webSocketDebuggerUrl"], timeout=60)
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "window.__jzErrs=[];"
            "addEventListener('error',function(e){window.__jzErrs.push(String((e&&e.message)||e));});"
            "addEventListener('unhandledrejection',function(e){"
            "window.__jzErrs.push('promise: '+String((e&&e.reason)||e));});"
        )})

        def js(expr):
            r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                             "awaitPromise": True})
            return r.get("result", {}).get("value")

        def shot(name):
            r = ws.call("Page.captureScreenshot", {"format": "png"})
            with open(os.path.join(SHOTS, name), "wb") as f:
                f.write(base64.b64decode(r["data"]))

        ws.call("Page.navigate", {"url": URL})
        time.sleep(3.5)
        ok("桌面已加载", (js("document.querySelectorAll('#icons .dicon').length") or 0) >= 1)

        # 打开 AI 面板（宽屏默认开，保险起见显式开）
        js("document.body.classList.add('ai-open'); true")
        time.sleep(0.5)

        # 真的往输入框里打字 + 回车（走和用户一样的 keydown 路径）
        js("document.getElementById('aiInput').focus(); true")
        ws.call("Input.insertText", {"text": PROMPT})
        time.sleep(0.3)
        ws.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter",
                                           "code": "Enter", "windowsVirtualKeyCode": 13})
        ws.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter",
                                           "code": "Enter", "windowsVirtualKeyCode": 13})
        print("已发送，等待 AI 规划并出图（最多 5 分钟）…")

        # 轮询：等到所有步骤卡片都不再「进行中」，且缩略图数量够、都真加载出来
        want = int(os.environ.get("JZ_EXPECT", "2"))
        deadline = time.time() + 300
        seen_card = False
        while time.time() < deadline:
            n_card = js("document.querySelectorAll('.step-card').length") or 0
            if n_card and not seen_card:
                seen_card = True
                print(f"  出现 {n_card} 个步骤卡片")
            loaded = js("(function(){var a=[].slice.call(document.querySelectorAll('.sc-img img'));"
                        "return a.filter(function(i){return i.naturalWidth>0;}).length;})()") or 0
            running = js("document.querySelectorAll('.step-card.running').length") or 0
            if loaded and (loaded >= want and not running):
                print(f"  {loaded} 张缩略图已加载完成")
                break
            time.sleep(2)

        n_img = js("document.querySelectorAll('.sc-img img').length") or 0
        n_ok = js("(function(){var a=[].slice.call(document.querySelectorAll('.sc-img img'));"
                  "return a.filter(function(i){return i.naturalWidth>0;}).length;})()") or 0
        ok("AI 调用了工具", seen_card)
        ok(f"至少生成 {want} 张图", n_img >= want, f"实际 {n_img} 张")
        ok("对话里的缩略图真的加载成功", n_ok >= min(want, n_img) and n_ok > 0, f"{n_ok}/{n_img}")
        shot("20-image-chat.png")

        # 点缩略图，应该打开图片查看器
        before = js("JZ.WM.wins.size") or 0
        js("(function(){var b=document.querySelector('.sc-img');if(b){b.click();return 'ok';}return 'none';})()")
        time.sleep(1.5)
        after = js("JZ.WM.wins.size") or 0
        ok("点缩略图能打开查看器", after >= before and (js(
            "(function(){for (var w of JZ.WM.wins.values()){if(w.appId==='viewer')return true;}return false;})()") is True))
        vw = js("(function(){var i=document.querySelector('.viewer img');return i?i.naturalWidth:0;})()") or 0
        ok("查看器里大图加载成功", vw > 0, vw)
        shot("21-image-viewer.png")

        errs = js("window.__jzErrs") or []
        ok("全程无 JS 异常", not errs, errs[:3])
        print(f"\n截图: {SHOTS}/20-image-chat.png, 21-image-viewer.png")
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        proc.terminate()

    total = len(PASS) + len(FAIL)
    print(f"\n{'='*46}\n图像验收: {len(PASS)}/{total} 通过")
    if FAIL:
        print("失败项: " + "、".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
