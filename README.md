# 饺子AIWorld

**给 Linux 加一个像 Windows 一样的桌面，人和 AI 共用同一张桌子。**
同一套代码跑在电脑、安卓手机、树莓派 / RK3588 这类开发板上；模型可以完全跑在本地，断网也能干活。

![桌面](docs/images/desktop.png)

---

## 这是什么，为什么不是"又一个套壳"

大多数"AI + Linux"方案是两套东西拼起来：一边是操作系统，一边是一个聊天窗口。人和 AI 各干各的，AI 只能给你返回一段文字，你还得自己去终端里执行。

饺子AIWorld 换个思路：**桌面本身就是 AI 的操作界面**。

- 人类和应用通过 HTTP/SSE 操作桌面；
- AI 通过**同一批接口**操作桌面；
- 所以 AI 打开的窗口你看得见，AI 改的文件你在文件管理器里立刻看到，AI 执行的命令会出现在通知里；
- 反过来，你手动改了文件，AI 下一轮读到的就是新内容——不需要同步、不需要上传、没有"两个世界"。

技术上做了一个关键的取舍：**不用 X11 / Wayland 那一套，用浏览器内核做渲染层**。
理由很实际：X11 在安卓上要靠 proot+chroot 折腾，在开发板上要装一堆驱动，分辨率一变 UI 就崩。
而 Chromium 在这三类设备上都已经跑得很好，还能天然支持"手机远程连同一个桌面"。
代价是它不是一个能跑 Photoshop 的传统桌面——它的定位是**设备控制台 + AI 工作面**，不是替代 GNOME。

---

## 30 秒跑起来

只依赖 Python 3.8+ 标准库。**没有 pip install，没有 npm install，没有构建步骤。**

```bash
git clone <这个仓库> && cd jiaozi-aiworld
python3 -m jiaozi --open
```

浏览器会打开 `http://127.0.0.1:8787/`，就是上面那张桌面。

### 电脑（Linux / macOS）

```bash
./scripts/install.sh            # 装启动器和桌面图标
jiaozi --open                   # 以后直接这样启动
./scripts/install.sh --service  # 可选：systemd 开机自启
```

Windows 也能跑（开发预览用，终端走管道而非 PTY）：

```powershell
python -m jiaozi --open
```

### 安卓手机

不需要 root，不需要 proot，核心就是纯 Python：

```bash
# 手机装 Termux（F-Droid 版）→ 把项目目录传进去
bash scripts/android-termux.sh /path/to/jiaozi-aiworld
```

然后手机浏览器打开 `http://127.0.0.1:8787/`，菜单里"添加到主屏幕"，就是全屏 App 的感觉。
Termux 里有真 PTY，所以终端是完整可用的。

### 开发板（树莓派 / Orange Pi / RK3588）

```bash
sudo apt install -y python3 chromium
./scripts/install.sh --kiosk --service
jiaozi-kiosk        # 全屏独占，接上屏幕就是一台设备
```

接 HDMI 屏 + 触摸屏，开机直接进桌面。详见 [docs/DEVBOARD.md](docs/DEVBOARD.md)。

### 局域网共享（手机 + 电脑同一个桌面）

```bash
python3 -m jiaozi --host 0.0.0.0
```

启动时会打印一个带 token 的手机访问地址。手机打开后看到的是**同一个桌面**：
同一份文件、同一个 AI 会话、同一批窗口事件。手机上让饺子整理照片，电脑上立刻能看到。

---

## 桌面上有什么

| 应用 | 说明 |
|---|---|
| **文件管理器** | 目录树、面包屑、搜索、上传/下载、拖拽上传、重命名、删除进回收站、实时跟随 AI 的文件改动 |
| **终端** | 自研 VT 解析器（256 色/真彩/光标控制/宽字符），POSIX 上是真 PTY，断线重连自动补齐输出 |
| **编辑器** | 行号、语法等宽、Ctrl+S、脏标记、行列表统计 |
| **系统监视器** | CPU/内存/磁盘实时曲线、进程表、结束进程 |
| **设置** | 模型端点、审批策略、主题壁纸、沙箱根目录，改完立即生效 |
| **图片查看器** | 缩放、适应窗口、外部打开 |
| **饺子 AI** | 右侧常驻面板：流式回复、工具步骤卡片、危险操作审批 |

窗口管理器是自己写的：拖拽、八向缩放、贴边分屏、最大化、层叠、任务栏切换、右键菜单。
主题有浅色/深色，五套壁纸，全部纯 CSS。

<table>
<tr><td><img src="docs/images/files.png" alt="文件管理器"></td><td><img src="docs/images/terminal.png" alt="终端"></td></tr>
<tr><td><img src="docs/images/dark.png" alt="深色主题"></td><td><img src="docs/images/mobile.png" alt="手机竖屏桌面"></td></tr>
</table>

手机上是同一套代码，不是另做一个 App：窄屏自动换成手机桌面（图标四列）、
文件管理器侧栏收成顶部快捷入口、AI 面板全屏并留一个"桌面"按钮退出。
下面这张就是手机竖屏下打开文件管理器的样子（浏览器 F12 切到 390×844 可以自己看）：

<p align="center"><img src="docs/images/mobile-files.png" alt="手机上的文件管理器" width="300"></p>

---

## AI 到底能做什么

不是"能聊天"，是**能动手**。内置 12 个工具，全部走和人类一样的后端接口：

| 工具 | 作用 | 危险 |
|---|---|---|
| `fs_list` `fs_read` `fs_search` | 看目录、读文件、按名搜索 | |
| `fs_write` `fs_mkdir` | 写文件、建目录 | |
| `shell_run` | 执行 shell 命令 | ⚠ |
| `sys_info` `proc_list` `proc_kill` | 系统信息、进程、结束进程 | ⚠ |
| `ui_open` | 在人类桌面上打开窗口/文件 | |
| `ui_notify` | 弹通知汇报进度 | |
| `web_fetch` | 抓网页正文 | ⚠ |

三个设计细节值得说：

**1. 小模型也能用。** 很多 1B~3B 模型不支持 OpenAI 的 `tools` 参数。这里做了双协议：
能原生调用就走 function calling；不支持的自动降级成提示协议（模型输出 ```json {"tool":...}``` 代码块，服务端解析）。
模型报错说"不支持 tools"时会自动切换并重试一次，用户无感。

**2. 危险操作必须过人。** 三种策略：`auto`（只有危险操作问）、`always`（全都问）、`never`（放手）。
审批卡片直接出现在对话流里，显示要执行的完整命令，点允许才继续。同一次会话里同一个工具批准过一次就不再烦你。

**3. 上下文是省的。** 只保留最近 14~24 条消息，工具结果超过 3000 字截断。1.5B 模型的 4K 窗口也扛得住多步任务。

配模型（本机 Ollama 举例）：

```bash
./scripts/get-model.sh qwen2.5:1.5b-instruct
# 然后在 设置 → AI 模型 里填 http://127.0.0.1:11434/v1
```

推荐档位见 [docs/MODELS.md](docs/MODELS.md)。

---

## 机器人 / 设备怎么用

这是这个项目真正的野心：**给没有脑子的设备装一个本地脑子。**

```bash
# 设备侧只需要发一句话，拿最终结果
curl -X POST http://127.0.0.1:8787/api/device/task \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"检查磁盘剩余空间，低于 10% 就清理 /tmp 里的旧日志","device":"arm-bot-01"}'
```

```json
{"ok": true, "result": "磁盘剩余 15.2%，无需清理。", "steps": 2, "elapsed": 3.4}
```

设备端唯一的要求是能发 HTTP。模型、工具、审批、日志全部在板上。
一块 8G 内存的 RK3588 跑 1.5B 模型 + 本服务，整机功耗十几瓦，离线可用。
算力不够就两台串起来：一台跑模型当"大脑"，一台跑桌面/外设当"身体"，走同一个 API。

---

## 项目结构

```
jiaozi-aiworld/
├── jiaozi/
│   ├── server.py         HTTP 内核：路由、SSE、静态资源、鉴权（纯标准库）
│   ├── shell.py          PTY / 管道会话管理 + 输出环形缓冲
│   ├── fsapi.py          沙箱文件系统（越界直接拒绝）
│   ├── sysinfo.py        CPU/内存/磁盘/进程（Linux 读 /proc，Windows 走降级实现）
│   ├── config.py         配置与运行时路径
│   ├── eventbus.py       进程内事件总线（SSE 推送）
│   ├── agent/
│   │   ├── llm.py        OpenAI 兼容客户端（流式 + tool_calls 增量拼装 + 本地代理绕过）
│   │   ├── tools.py      12 个工具的定义与调度
│   │   ├── loop.py       Agent 循环、双协议、审批、上下文裁剪
│   │   └── prompts.py    提示词
│   └── desktop/          前端（无框架、无构建）
│       ├── index.html
│       ├── css/          base / desktop / apps
│       └── js/
│           ├── core.js     API、SSE、toast、模态、右键菜单、Markdown
│           ├── vt.js       VT 屏幕缓冲与解析器（独立可单测）
│           ├── wm.js       窗口管理器
│           ├── shell.js    桌面外壳：图标/任务栏/开始菜单/通知
│           ├── agent.js    AI 面板
│           └── apps/       6 个内置应用
├── scripts/              安装、安卓、kiosk、模型
├── tests/                冒烟测试、VT 单测、界面 E2E
└── docs/                 架构、安装、开发板、API、模型
```

---

## 验证到什么程度

我不是"写完就交"。仓库里带三套能自己跑的测试，全部当前通过：

```bash
python3 tests/smoke_test.py     # 52 项：HTTP、沙箱、终端、Agent 循环、审批、设备、鉴权
node tests/vt_test.js           # 24 项：VT 解析、颜色、光标、宽字符、HTML 转义
python3 tests/ui_test.py        # 36 项：真实浏览器加载、点开应用、真敲键盘、手机竖屏、截图
```

`smoke_test.py` 内置了一个假的 OpenAI 兼容模型服务，所以**没有真模型也能验证完整 Agent 链路**：
它会让"模型"请求 `fs_list`，服务端真的去列目录，把结果回给"模型"，"模型"再给最终答复。
审批流程同样是真的：测试在事件流里收到审批请求后发 HTTP 批准，命令才真的执行。
最后一段会临时关掉 localhost 放行，验证手机远道访问那条路：无凭据拒绝、错误 token 拒绝、
`?token=` 换 cookie、cookie 放行——这是"手机连电脑"能不能用的关键，不能靠猜。

`ui_test.py` 用一个 200 行的迷你 CDP 客户端驱动无头 Chrome：真实导航、真实 `keydown`、
真实截图。终端里那句 `echo JIAOZI-UI-OK` 是走用户完全相同的键盘路径打进去的。
最后一段把视口切成 390×844 的手机竖屏再量一遍：首屏是不是桌面、有没有横向溢出、
窗口有没有跑出屏幕、文件名还在不在、终端列数有没有按窄屏重算。

**已验证：** Linux/Windows 上的服务、沙箱越权拦截、PTY 与管道终端、双协议 Agent、
审批阻断、深色主题、窗口拖拽缩放最大化、8 个应用、手机/PC 同源访问、手机竖屏布局。

这套测试不是摆着看的——它们真的抓到过 bug（详见 `docs/ARCHITECTURE.md` 末尾"实测踩到的坑"）。

**还没验证（需要你的硬件）：** 真安卓机、树莓派/RK3588 实机、真实小模型下的多步任务成功率、
触摸屏手势、长时间（>24h）稳定性。这些我不敢说"肯定行"，文档里写清了预期和风险。

---

## 边界与取舍

- **不是通用 Linux 桌面。** 跑不了 GIMP/IDE 这类 X11 原生程序。它是设备控制台。
- **浏览器内核是硬依赖。** 板子上要装 Chromium（约 100MB）。
- **安全模型很朴素。** 单 token + 目录白名单，HTTP 明文。它是给可信局域网/单机用的，别直接扔公网。
- **全屏 TUI 有局限。** 自研 VT 不支持滚动区域和鼠标上报，vim/htop 会显示异常；bash、日志、编译输出没问题。
- **Windows 是预览档位。** 终端走管道，没有 job control。

---

## 接下来

- [ ] 触摸手势（长按菜单、双指缩放）
- [ ] 窗口位置持久化，重启后恢复现场
- [ ] 多设备会话：让手机上的 AI 操作电脑上的窗口
- [ ] 语音入口（本地 whisper.cpp + 流式 TTS）
- [ ] 技能包：把常用任务固化成可复用脚本，AI 直接调用
- [ ] 板端一键镜像（树莓派 / RK3588 的 img）

---

## 协议

MIT。拿去用，拿去改，拿去装在你的机器人上。

如果它让你少写一个云端调用、少一次断网抓瞎，这个项目就值了。
