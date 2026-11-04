# 开发板部署

目标：一块 ARM 板 + 一个屏幕，开机就是一台能自己思考的设备。

## 硬件档位

| 档位 | 例子 | 内存 | 能跑什么 | 体验 |
|---|---|---|---|---|
| 入门 | 树莓派 Zero 2 W / Orange Pi Zero 3 | 512M~1G | 远程访问，模型放另一台机器 | 桌面能开，模型别指望 |
| 主流 | 树莓派 4B 4G / Orange Pi 5 | 4G | Qwen2.5-0.5B / 1.5B (Q4) | 1.5B 约 4~8 token/s，简单任务可用 |
| 推荐 | 树莓派 5 8G / RK3588 (Orange Pi 5 Plus) | 8~16G | Qwen2.5-3B (Q4)，RK3588 可用 NPU | 3B 多步任务基本靠谱 |
| 带屏设备 | Jetson Orin Nano / x86 迷你主机 | 8G+ | 7B (Q4) | 接近桌面体验 |

一条经验：**内存 ≥ 模型参数量 × 0.7GB（Q4 量化）+ 1.5GB 系统余量**。
1.5B 需要约 2.5GB 空闲，3B 约 3.5GB，7B 约 6.5GB。

## 一、装系统

用官方镜像（Raspberry Pi OS Lite 64-bit / Armbian / Orange Pi 官方 Ubuntu），
**选 Lite 版**——不需要桌面环境，桌面由本项目提供。

```bash
sudo apt update && sudo apt install -y python3 chromium fonts-noto-cjk
```

`fonts-noto-cjk` 必装，否则中文是方框。

## 二、装本项目

```bash
git clone <repo> ~/jiaozi-aiworld && cd ~/jiaozi-aiworld
./scripts/install.sh --kiosk --service
```

- `--kiosk` 生成 `jiaozi-kiosk`：先起服务，再用 Chromium `--kiosk --app=` 全屏打开
- `--service` 注册 systemd，开机自动起服务（监听 0.0.0.0，方便同网段其他设备接入）

想开机直接进桌面而不是先登录 shell，编辑 `~/.config/wayfire.ini`（或 `~/.xinitrc`）把
`jiaozi-kiosk` 作为会话启动项；更干净的做法是用 `cage` 这类单应用 Wayland 合成器：

```bash
sudo apt install -y cage
# /etc/systemd/system/jiaozi-kiosk.service
[Service]
ExecStart=/usr/bin/cage -- /home/pi/.local/bin/jiaozi-kiosk
```

## 三、装模型

```bash
# 方式 A：Ollama（简单）
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct

# 方式 B：llama.cpp（CPU 上更快，可控参数多）
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build -DGGML_NATIVE=ON && cmake --build build -j4
./build/bin/llama-server -m Qwen2.5-1.5B-Instruct-Q4_K_M.gguf \
    --host 127.0.0.1 --port 8080 -c 4096 -t 4 --jinja
```

然后在桌面「设置 → AI 模型」里填：

| | Ollama | llama.cpp |
|---|---|---|
| 服务地址 | `http://127.0.0.1:11434/v1` | `http://127.0.0.1:8080/v1` |
| 模型名 | `qwen2.5:1.5b-instruct` | 随便填，服务端只有一个模型 |
| 原生函数调用 | 开 | 开（llama.cpp 需 `--jinja`） |

点「测试连接」，看到"连接正常"就成了。

## 四、性能调优

**关掉毛玻璃**（无 GPU 的板子收益最大）：编辑 `jiaozi/desktop/css/base.css`，
把 `backdrop-filter` 相关行删掉或改成 `none`。

**减少渲染面积**：默认只开一个窗口；AI 面板在小屏上会自动全屏。

**控制上下文**：设置里 `max_steps` 调到 6~8，`max_tokens` 调到 512，延迟会明显下降。

**线程数**：llama.cpp 的 `-t` 设成物理核心数（不是超线程数），RK3588 用 `-t 4`。

**温度**：满载跑模型时板子会降频，加散热片/风扇比任何软件优化都有效。

## 五、接屏幕和触摸

- HDMI 屏：即插即用，Chromium 会按屏幕分辨率渲染。
- 电容触摸屏：Linux 内核识别为 `/dev/input/eventX` 后，Chromium 直接支持单点触摸；
  本项目所有交互都用 Pointer Events，所以触摸可用。
- 建议在 `index.html` 里已设置的 `viewport-fit=cover` 前提下，用 `--kiosk` 全屏，
  避免浏览器地址栏吃掉竖向空间。

## 六、给机器人用

设备（MCU / ROS 节点 / 树莓派从机）只需要 HTTP：

```python
import requests

r = requests.post("http://127.0.0.1:8787/api/device/task",
                  json={"prompt": "读取 /data/sensor.log 最后 20 行，总结异常",
                        "device": "arm-01"},
                  timeout=120)
print(r.json()["result"])
```

- `device` 参数会为每台设备开一个独立会话，上下文互不污染。
- 同步接口，适合"叫一次、等结果"的机器人流程。
- 需要流式/长任务，改用 `/api/agent/chat`（SSE），或自己轮询 `/api/agent/history`。

## 七、多板串联（算力不够时）

```
   感知板 (RK3588, 8G)                执行板 (树莓派, 2G)
   ├─ llama.cpp 3B                    ├─ 本服务（无模型）
   ├─ 摄像头 / 传感器                  ├─ GPIO / 电机 / 云台
   └─ 跑业务逻辑                       └─ /api/device/task 指向感知板
        :8787  ◄──────── HTTP ────────┘
```

两块板各跑一份本项目也可以：感知板做"大脑"（配置里有模型），
执行板只做"身体"（配置里指向对方），桌面可以开在任意一台上。

## 八、故障排查

| 现象 | 检查 |
|---|---|
| 开机黑屏 | `systemctl status jiaozi`；Chromium 是否装了；`jiaozi-kiosk` 手动跑一次看报错 |
| 中文方块 | `fc-list :lang=zh` 有没有输出，没有就装 `fonts-noto-cjk` |
| 页面卡顿 | 关毛玻璃、关多余窗口、`top` 看是不是模型吃满了 CPU |
| 模型 502 | 模型服务没起，或地址端口写错；`curl http://127.0.0.1:11434/v1/models` |
| 终端没输出 | 板子上 `pty` 是否可用（`python3 -c "import pty"`）；看服务端日志 |
| 手机连不上 | 防火墙 `sudo ufw allow 8787`；确认是同一个网段 |
| 内存耗尽 | 降模型量化等级（Q4→Q3），或换更小模型；限制 `max_steps` |
