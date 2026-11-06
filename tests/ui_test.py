#!/usr/bin/env python3
"""界面端到端测试（需要本机 Chrome/Edge）。

用 DevTools 协议真实加载页面、真实敲键盘、真实截图。
无头模式的 --virtual-time-budget 会把定时器压缩，测不出终端这类实时内容；
所以这里用 CDP + 真实等待。

    python tests/ui_test.py                 # 跑全部并输出截图到 tests/shots/
    python tests/ui_test.py --keep-open     # 不关闭浏览器
"""
from __future__ import annotations

import base64
import glob
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from base64 import b64encode

# 本机回环请求绝不能被送进 HTTP 代理。
# 开发机上常开着 http_proxy（翻墙/抓包），no_proxy 又往往是空的，
# 结果 127.0.0.1:9333 也走代理 → 调试端口"起不来"，实际是查找不到自己。
for _k in ("no_proxy", "NO_PROXY"):
    _hosts = {h.strip() for h in os.environ.get(_k, "").split(",") if h.strip()}
    _hosts |= {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    os.environ[_k] = ",".join(sorted(_hosts))
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

URL = os.environ.get("JIAOZI_URL", "http://127.0.0.1:8787").rstrip("/") + "/"
PORT = int(os.environ.get("CDP_PORT", "9333"))
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(SHOTS, exist_ok=True)

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  \033[92m✓\033[0m " if cond else "  \033[91m✗\033[0m ") + name +
          ("" if cond else "  — " + str(detail)[:300]))


def find_browser() -> str | None:
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- 迷你 WebSocket
class WS:
    def __init__(self, url: str, timeout: float = 20.0):
        assert url.startswith("ws://"), url
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = b64encode(bytes(random.getrandbits(8) for _ in range(16))).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败")
            buf += chunk
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket 握手被拒绝: " + head.decode("utf-8", "replace")[:200])
        self._id = 0

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("连接已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        header = b"\x81"
        mask = bytes(random.getrandbits(8) for _ in range(4))
        n = len(data)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def recv(self) -> str:
        payload = b""
        while True:
            b1, b2 = self._recv_exact(2)
            fin = b1 & 0x80
            op = b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recv_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recv_exact(8))[0]
            if b2 & 0x80:
                mask = self._recv_exact(4)
                raw = self._recv_exact(ln)
                raw = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
            else:
                raw = self._recv_exact(ln)
            if op == 0x9:  # ping
                self.sock.sendall(b"\x8a\x80" + b"\x00\x00\x00\x00")
                continue
            if op == 0x8:
                raise ConnectionError("收到关闭帧")
            payload += raw
            if fin:
                return payload.decode("utf-8", "replace")

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0):
        self._id += 1
        mid = self._id
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self.sock.sendall(b"\x88\x80\x00\x00\x00\x00")
            self.sock.close()
        except OSError:
            pass


def reset_profile(path):
    """清掉上一轮留下的 SingletonLock。

    Chrome 的进程单例是按 user-data-dir 认的：上一轮被 kill -9 之后
    目录里会留着锁，下一次启动以为"已有会话在跑"，把命令转交出去然后
    自己退出（退出码 21，没有任何输出）。表现就是"调试端口起不来"。
    这个目录是本测试自己建的，删掉是安全的。
    """
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def wait_cdp(timeout=20.0, proc=None, log_path=""):
    end = time.time() + timeout
    while time.time() < end:
        # 浏览器自己先挂了就别干等到超时，直接把退出码和日志尾巴报出来。
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                "Chrome 启动即退出（代码 %s）\n%s" % (proc.returncode, _tail(log_path)))
        try:
            with _OPENER.open(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as r:
                data = json.loads(r.read())
            pages = [t for t in data if t.get("type") == "page"]
            if pages:
                return pages[0]
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError("Chrome 调试端口没起来（端口 %d）\n%s" % (PORT, _tail(log_path)))


def _tail(path, n=2500):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return "(无日志)"


def main() -> int:
    exe = find_browser()
    if not exe:
        print("没有找到 Chrome/Edge，跳过界面测试")
        return 0
    if not URL.startswith("http"):
        print("URL 不合法")
        return 1

    prof = os.path.join(tempfile.gettempdir(), "jz_cdp_profile")
    reset_profile(prof)
    blog = os.path.join(tempfile.gettempdir(), "jz_cdp_stderr.log")
    _blog = open(blog, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([
        exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
        "--window-size=1440,900", "--hide-scrollbars", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=_blog)

    ws = None
    try:
        page = wait_cdp(proc=proc, log_path=blog)
        ws = WS(page["webSocketDebuggerUrl"], timeout=40)
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        # 在页面脚本之前装一个错误收集器：静默的 JS 异常最难发现，
        # 元素都在但功能坏掉，全靠这一条兜住。
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "window.__jzErrs=[];"
            "addEventListener('error',function(e){"
            "  window.__jzErrs.push(String((e&&e.message)||e));"
            "});"
            "addEventListener('unhandledrejection',function(e){"
            "  window.__jzErrs.push('promise: '+String((e&&e.reason)||e));"
            "});"
        )})
        print(f"调试目标: {page.get('url')}")

        def goto(url, wait=3.0):
            ws.call("Page.navigate", {"url": url})
            time.sleep(wait)

        def js(expr):
            r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                             "awaitPromise": True})
            return r.get("result", {}).get("value")

        def shot(name):
            r = ws.call("Page.captureScreenshot", {"format": "png"})
            path = os.path.join(SHOTS, name)
            with open(path, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            return path

        print("\n[UI-1] 桌面加载")
        # 先把界面语言钉成中文。
        # 下面这套断言都是按中文写的，而语言默认是"跟着浏览器走"的：
        # 开发机上是 zh-CN，CI 上的无头 Chrome 是 en-US，同一份代码在一台
        # 机器上全绿、在另一台上红三条——不是功能坏了，是断言没定住前提。
        # 多语言本身由 [UI-8] 专门测，那里会真切到德语再切回来。
        goto(URL, 2.0)
        js("try{localStorage.setItem('jz.lang','zh-CN')}catch(e){}")
        goto(URL, 3.5)
        ok("标题正确", js("document.title") in ("饺子AIWorld", "Jiaozi AI World"),
           js("document.title"))
        ok("已离开开机画面", js("!document.body.classList.contains('booting')"))
        ok("桌面图标渲染", (js("document.querySelectorAll('#icons .dicon').length") or 0) >= 6,
           js("document.querySelectorAll('#icons .dicon').length"))
        ok("任务栏应用存在", (js("document.querySelectorAll('#tbApps .tb-app').length") or 0) >= 5)
        ok("AI 面板打开", js("document.body.classList.contains('ai-open')"))
        ok("无 JS 异常", not (js("window.__jzErrs") or []),
           (js("window.__jzErrs") or [])[:3])
        ok("PWA 清单可加载", js("fetch('/manifest.webmanifest').then(function(r){return r.status})") == 200)
        ok("图标可加载", js("fetch('/icon.svg').then(function(r){return r.status})") == 200)
        shot("01-desktop.png")

        print("\n[UI-2] 文件管理器")
        js("JZ.WM.open('files')")
        time.sleep(2.2)
        rows = js("document.querySelectorAll('.fm-row').length")
        ok("文件列表有内容", (rows or 0) > 0, rows)
        ok("路径面包屑存在", (js("document.querySelectorAll('.fm-crumb button').length") or 0) > 1)
        ok("磁盘信息已显示", bool(js("(document.querySelector('.st-disk')||{}).textContent")))
        shot("02-files.png")

        print("\n[UI-3] 终端真实交互")
        js("JZ.WM.open('terminal')")
        time.sleep(3.5)   # 等 bash 真正启动
        ok("终端会话已建立", bool(js("(document.querySelector('.tt-size')||{}).textContent")))
        # 通过真实 keydown 事件把命令喂给 shell（走与用户完全相同的代码路径）
        js("""(function(){
            var ta = document.querySelector('.term-input');
            if (!ta) return 'no-input';
            ta.focus();
            var s = 'echo JIAOZI-UI-OK';
            for (var i=0;i<s.length;i++){
              ta.dispatchEvent(new KeyboardEvent('keydown',{key:s[i],bubbles:true}));
            }
            ta.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
            return 'sent';
        })()""")
        txt = ""
        for _ in range(30):
            time.sleep(0.25)
            txt = js("(document.querySelector('.term-live')||{}).textContent || ''") or ""
            if "JIAOZI-UI-OK" in txt and txt.count("JIAOZI-UI-OK") >= 2:
                break
        ok("命令已执行并回显", "JIAOZI-UI-OK" in txt, txt[-200:])
        # root 的提示符是 #，普通用户是 $，Windows PowerShell 是 >，三种都要认
        ok("终端有提示符输出",
           "bash" in txt.lower() or "$" in txt or ">" in txt or "#" in txt, txt[:120])
        shot("03-terminal.png")

        print("\n[UI-4] 设置与监视器")
        js("JZ.WM.open('settings')")
        time.sleep(1.2)
        ok("设置表单加载", (js("document.querySelectorAll('.set-field .input').length") or 0) >= 5)
        ok("模型地址已填", "http" in (js("(document.querySelector('[data-f=\\'base_url\\']')||{}).value") or ""))
        shot("04-settings.png")

        # 图像生成页：新加的，得有人守着，否则字段被改坏也没人知道
        js("(function(){var b=[].slice.call(document.querySelectorAll('.set-nav'))"
           ".filter(function(n){return n.dataset.tab==='image';})[0]; if(b)b.click();"
           "return !!b;})()")
        time.sleep(0.6)
        ok("设置里有「图像生成」页",
           js("!!document.querySelector('[data-pane=\"image\"]')") is True)
        ok("图像页字段齐全（地址/模型/Key/尺寸/目录）",
           (js("document.querySelectorAll('[data-pane=\"image\"] .set-field .input').length") or 0) >= 5)
        ok("API Key 输入框不回填脱敏星号",
           not (js("(document.querySelector('[data-f=\\'img_api_key\\']')||{}).value") or "").startswith("****"))
        ok("图像页可切回模型页",
           (js("(function(){var b=document.querySelector('.set-nav[data-tab=\"llm\"]');"
               "if(b)b.click(); return !document.querySelector('[data-pane=\"llm\"]').hidden;})()")) is True)
        js("JZ.WM.open('monitor')")
        time.sleep(2.5)
        ok("进程表有数据", (js("document.querySelectorAll('.mon-table tbody tr').length") or 0) > 1,
           js("document.querySelectorAll('.mon-table tbody tr').length"))
        ok("CPU 数值已渲染", "%" in (js("(document.querySelector('[data-role=\\'cpu\\']')||{}).textContent") or ""))
        shot("05-monitor.png")

        print("\n[UI-5] 深色主题")
        js("document.documentElement.dataset.theme='dark'; JZ.pref.set('theme','dark');")
        time.sleep(0.8)
        ok("深色主题生效", js("document.documentElement.dataset.theme") == "dark")
        shot("06-dark.png")
        js("document.documentElement.dataset.theme='light'; JZ.pref.set('theme','light');")

        print("\n[UI-6] 窗口操作")
        before = js("JZ.WM.wins.size")
        js("JZ.WM.open('editor')")
        time.sleep(1.0)
        ok("新窗口可创建", (js("JZ.WM.wins.size") or 0) > (before or 0))
        ok("窗口可最大化", bool(js("(function(){var w=JZ.WM.active;w&&JZ.WM.toggleMax(w);return w&&w.maxed;})()")))
        shot("07-maximized.png")
        js("(function(){var w=JZ.WM.active;if(w){JZ.WM.toggleMax(w);JZ.WM.close(w);}return true;})()")
        time.sleep(0.4)
        ok("窗口可关闭", (js("JZ.WM.wins.size") or 0) == (before or 0))
        ok("交互全程无 JS 异常", not (js("window.__jzErrs") or []),
           (js("window.__jzErrs") or [])[:3])

        print("\n[UI-6b] 设备（局域网互认）")
        js("JZ.WM.open('devices')")
        time.sleep(1.6)
        ok("设备窗口打开", (js("document.querySelectorAll('.dev').length") or 0) > 0)
        ok("本机卡片有地址", bool(js(
            "(function(){var e=document.querySelector('.dev-me small');"
            "return e&&e.textContent.length>6;})()")))
        ok("生成配对码按钮存在", js(
            "!!document.querySelector('[data-act=\"code\"]')") is True)
        ok("手动配对输入框存在", (js("document.querySelectorAll('.dev-add .input').length") or 0) >= 3)

        js("document.querySelector('[data-act=\"code\"]').click()")
        time.sleep(1.2)
        code_txt = js("(function(){var e=document.querySelector('.dc-num');"
                      "return e?e.textContent.trim():'';})()")
        ok("弹出 6 位配对码", bool(code_txt) and len(code_txt) == 6 and code_txt.isdigit(), code_txt)
        # 不匹配"剩余"这两个字：文案是翻译过的，换个语言就失配。
        # 要验的是"有一行带数字的倒计时说明"，不是它用哪种语言写的。
        ok("配对码带倒计时说明", bool(js(
            "(function(){var e=document.querySelector('.dc-tip');"
            "if(!e) return false;var t=e.textContent||'';"
            "return t.length>6 && /\\d/.test(t);})()")),
           js("(document.querySelector('.dc-tip')||{}).textContent"))
        ok("设备列表有内容（空态也算）", (js("document.querySelectorAll('.dev-item, .dev .empty').length") or 0) > 0)
        ok("设备页无 JS 异常", not (js("window.__jzErrs") or []),
           (js("window.__jzErrs") or [])[:3])
        shot("07b-devices.png")
        js("(function(){var w=JZ.WM.active;if(w)JZ.WM.close(w);return true;})()")
        time.sleep(0.3)

        # 手机竖屏：这是「同一套系统跑安卓」的核心理由，必须真的量一遍
        print("\n[UI-7] 手机竖屏（390×844）")
        js("(function(){var a=document.querySelectorAll('#icons .dicon');return a.length;})()")
        ws.call("Emulation.setDeviceMetricsOverride", {
            "width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True,
        })
        ws.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        goto(URL, 3.5)

        vw = js("window.innerWidth") or 0
        ok("视口宽度生效", 380 <= vw <= 400, vw)
        ok("无横向溢出",
           (js("document.documentElement.scrollWidth") or 0) <= vw + 1,
           js("document.documentElement.scrollWidth"))
        # 手机上首屏必须是桌面，不是被全屏聊天框盖住
        ok("首屏先给桌面", not js("document.body.classList.contains('ai-open')"))
        ok("任务栏仍在",
           (js("(document.querySelector('#taskbar')||{}).offsetHeight") or 0) > 20,
           js("(document.querySelector('#taskbar')||{}).offsetHeight"))
        ok("桌面图标可见",
           (js("document.querySelectorAll('#icons .dicon').length") or 0) >= 4)
        shot("08-mobile.png")

        # 点任务栏小圆球调出 AI：窄屏应铺满
        js("document.getElementById('trayAi').click()")
        time.sleep(1.0)
        ok("AI 面板可调出", js("document.body.classList.contains('ai-open')"))
        ok("AI 面板全屏化",
           (js("(document.querySelector('#aiPanel')||{}).offsetWidth") or 0) >= vw * 0.9,
           js("(document.querySelector('#aiPanel')||{}).offsetWidth"))
        ok("有返回桌面出口", (js("(document.querySelector('#aiClose')||{}).offsetWidth") or 0) > 40)
        shot("09-mobile-ai.png")

        js("document.getElementById('aiClose').click()")
        time.sleep(0.9)
        ok("可退回桌面", not js("document.body.classList.contains('ai-open')"))

        # 真实点击（触摸模拟下走同一套 click 路径）打开文件管理器。
        # 用 data-app 而不是按中文标题找按钮：标题是翻译过的，
        # 换一门语言就再也匹配不上——这里要测的是"点得开"，不是"叫得对"。
        js("""(function(){
            var el=document.querySelector('#tbApps .tb-app[data-app="files"]');
            if(el){el.click();return 'clicked';} return 'not-found';
        })()""")
        time.sleep(2.0)
        ok("点击可打开应用", (js("JZ.WM.wins.size") or 0) >= 1, js("JZ.WM.wins.size"))
        # 手机上侧栏曾把「名称」列挤成 0 宽，文件名整个消失——这里量真实宽度
        nm = js("""(function(){
            var s=document.querySelector('.fm-row .fm-name span:last-child');
            if(!s) return null;
            return {w: s.getBoundingClientRect().width, t: (s.textContent||'').trim()};
        })()""") or {}
        ok("文件名可见", nm.get("w", 0) > 24 and bool(nm.get("t")), nm)
        shot("10-mobile-files.png")

        # 窗口默认尺寸是给桌面的（960×600），手机上必须被夹进屏幕内
        over = js("""(function(){
            var m=0;
            JZ.WM.wins.forEach(function(w){
              var r=w.el.getBoundingClientRect();
              m=Math.max(m, r.right - window.innerWidth, r.bottom - window.innerHeight + 0);
            });
            return Math.round(m);
        })()""") or 0
        ok("窗口不超出屏幕", over <= 1, over)

        # 终端在窄屏上要按真实宽度算列数，否则字符会折行错乱
        js("JZ.WM.open('terminal')")
        time.sleep(3.0)
        sz = js("(document.querySelector('.tt-size')||{}).textContent") or ""
        cols = 0
        try:
            cols = int(sz.split("×")[0])
        except Exception:
            cols = 0
        ok("手机终端列数自适应", 20 <= cols <= 70, sz)
        shot("11-mobile-term.png")
        ws.call("Emulation.clearDeviceMetricsOverride")
        ws.call("Emulation.setTouchEmulationEnabled", {"enabled": False})

        # ----------------------------------------------------------
        # 多语言：这块最容易「看着对、其实是旧的」——切了语言但界面
        # 还是原文，或者翻了一半半边中文。所以断言必须落到真实文字上，
        # 不能只看 lang 变量。
        print("\n[UI-8] 多语言")
        goto(URL, 3.0)
        langs = js("JZ.i18n.supported") or []
        ok("支持 10 种语言", len(langs) >= 10, langs)
        ok("语言有明确来源（用户/浏览器/IP/默认）",
           (js("JZ.i18n.meta.source") or "") in ("user", "browser", "ip", "default"),
           js("JZ.i18n.meta.source"))

        js("JZ.i18n.setLang('de')")
        time.sleep(3.2)
        ok("切德语后语言标记正确", js("JZ.i18n.lang") == "de", js("JZ.i18n.lang"))
        ok("html[lang] 跟着变", js("document.documentElement.lang") == "de")
        ok("代码里的文案真的变德文", js("JZ.t('文件')") == "Dateien", js("JZ.t('文件')"))
        # 静态 HTML 里有三种标记：正文、title、placeholder。
        # 三种走的不是同一段代码，少测一种就可能漏掉整类元素。
        ok("静态 HTML 正文翻了（应用 → Apps）",
           js("(function(){var e=document.querySelector('[data-i18n=\\'应用\\']');"
              "return !!e && e.textContent===JZ.t('应用') && e.textContent!=='应用';})()") is True,
           js("(document.querySelector('[data-i18n=\\'应用\\']')||{}).textContent"))
        ok("静态 HTML 的 title 翻了",
           js("(function(){var e=document.querySelector('[data-i18n-title=\\'设置\\']');"
              "return !!e && e.title===JZ.t('设置') && e.title!=='设置';})()") is True,
           js("(document.querySelector('[data-i18n-title=\\'设置\\']')||{}).title"))
        # 断言不写死译文：词典随时会被改短（德文长词挤不进搜索框），
        # 只要"渲染出来的值 == 词典里的值，且不等于中文原文"就说明这条路通了。
        ok("静态 HTML 的 placeholder 翻了",
           js("(function(){var e=document.querySelector('[data-i18n-ph=\\'搜索应用和文件\\']');"
              "if(!e) return false;"
              "return e.placeholder===JZ.t('搜索应用和文件') && e.placeholder!=='搜索应用和文件';})()")
           is True,
           js("(document.querySelector('[data-i18n-ph=\\'搜索应用和文件\\']')||{}).placeholder"))
        ok("德语界面无 JS 异常", not (js("window.__jzErrs") or []),
           (js("window.__jzErrs") or [])[:3])
        shot("12-lang-de.png")

        # 缺译、词典 404 这些边角，出问题都是白屏或一串 key
        ok("缺译回落中文原文，不显示空白",
           js("JZ.t('这条肯定没人翻过')") == "这条肯定没人翻过")
        ok("占位符插值正常", js("JZ.t('{n} 分钟前',{n:3})") == "vor 3 Min.",
           js("JZ.t('{n} 分钟前',{n:3})"))
        ok("词典取不到时给空表、不抛错",
           js("JZ.i18n.load('xx-YY').then(function(d){return Object.keys(d).length===0})"
              ".catch(function(){return false})") is True)

        js("JZ.i18n.setLang('zh-CN')")
        time.sleep(3.2)
        ok("切回中文正常", js("JZ.i18n.lang") == "zh-CN" and js("JZ.t('文件')") == "文件",
           js("JZ.t('文件')"))
        ok("中文界面无 JS 异常", not (js("window.__jzErrs") or []),
           (js("window.__jzErrs") or [])[:3])
        shot("12b-lang-zh.png")

        # 设置页的语言下拉：用户手动选语言的实际入口
        js("JZ.WM.open('settings')")
        time.sleep(1.2)
        ok("设置里有「语言」页",
           js("!!document.querySelector('.set-nav[data-tab=\\'lang\\']')") is True)
        js("(function(){var b=document.querySelector('.set-nav[data-tab=\\'lang\\']');"
           "if(b)b.click();return !!b;})()")
        time.sleep(0.6)
        nopt = js("(document.querySelector('[data-f=\\'language\\']')||{options:[]})"
                  ".options.length") or 0
        ok("语言下拉含「自动」+ 10 种语言", nopt >= 11, nopt)
        ok("语言页显示当前语言是怎么定下来的",
           bool(js("(document.querySelector('.lang-now')||{}).textContent")),
           js("(document.querySelector('.lang-now')||{}).textContent"))
        shot("13-lang-settings.png")

        # 服务端接口：前端换语言要能被记住，重启后不该又跳回去
        ok("服务端记得住语言选择",
           js("fetch('/api/i18n',{method:'POST',headers:{'Content-Type':'application/json'},"
              "body:JSON.stringify({lang:'ja'})}).then(function(r){return r.json()})"
              ".then(function(j){return (j.data||j).lang})") == "ja")
        ok("IP 归属地接口有回应（断网也不能崩）",
           js("fetch('/api/geo').then(function(r){return r.json()})"
              ".then(function(j){return typeof (j.data||j).ok === 'boolean'})"
              ".catch(function(){return false})") is True)

        # 归位：别把测试用的语言选择留在浏览器和配置里
        js("fetch('/api/i18n',{method:'POST',headers:{'Content-Type':'application/json'},"
           "body:JSON.stringify({lang:'auto'})})")
        js("JZ.i18n.useAuto()")
        time.sleep(2.0)
    finally:
        if ws:
            ws.close()
        if "--keep-open" not in sys.argv:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            _blog.close()
        except OSError:
            pass

    total = len(PASS) + len(FAIL)
    print("\n" + "=" * 56)
    print(f"界面测试：{len(PASS)}/{total} 通过")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("截图已保存到 tests/shots/")
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
