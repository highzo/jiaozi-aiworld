# 安装

## 通用要求

- Python **3.8+**（不需要任何第三方包）
- 一个现代浏览器（Chrome / Edge / Chromium / Safari 16+ / 安卓 WebView 100+）

不需要 Node、不需要 npm、不需要编译。

```bash
python3 -m jiaozi --help
```

```
--host 0.0.0.0     局域网共享（默认只监听 127.0.0.1）
--port 8787        端口
--open             启动后打开浏览器
--token xxx        指定访问 token
--reset-token      重置 token
--config           打印配置位置与内容
```

首次启动会生成 `~/.jiaozi/config.json`，里面有随机 token。
本机回环地址默认免 token；局域网访问需要在 URL 上带 `?token=xxx`（启动时会打印完整链接，打开一次后写 Cookie）。

---

## Linux 桌面（Debian / Ubuntu / Arch / Fedora）

```bash
git clone <repo> && cd jiaozi-aiworld
./scripts/install.sh
jiaozi --open
```

安装脚本做了四件事：检查 Python 版本、跑一遍自检、写 `~/.local/bin/jiaozi`、写桌面图标。
加 `--service` 会注册 systemd 开机自启；加 `--kiosk` 生成全屏启动脚本。

手动跑也行：

```bash
python3 -m jiaozi --open
```

### 常见问题

**端口被占用** → `--port 8800`
**图标没出现** → `update-desktop-database ~/.local/share/applications`
**没有声音/输入法** → 与本项目无关，它是 Web UI，走的是浏览器输入法

---

## 安卓（Termux）

不需要 root，不需要 proot。

```bash
# 1. 装 Termux（务必用 F-Droid 或 GitHub 版本，Play 商店版已停更）
# 2. 把项目目录放到手机上，例如 ~/jiaozi-aiworld
pkg update && pkg install -y python
termux-setup-storage        # 允许访问 /sdcard
cd ~/jiaozi-aiworld
python3 -m jiaozi --host 0.0.0.0
```

浏览器打开 `http://127.0.0.1:8787/`。

一键脚本会额外做：自动把 `/sdcard` 加进沙箱、申请唤醒锁、打印局域网地址。

```bash
bash scripts/android-termux.sh ~/jiaozi-aiworld
```

### 想用完整 Linux 用户环境（apt 装工具）

```bash
pkg install proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
# 容器内：
apt update && apt install -y python3 git
# 把项目拷进容器，同样 python3 -m jiaozi
```

proot 里的 `/sdcard` 通常挂在 `/mnt/sdcard` 或 `/root`，记得在设置页把它加进沙箱。

### 安卓上的注意事项

- **后台被杀**：Termux 下拉通知里点 "Acquire wakelock"，并在系统设置里把 Termux 设为"不受限制"。
- **键盘遮挡**：Chrome 地址栏隐藏后（添加到主屏幕）体验最好。
- **终端**：Termux 提供真 PTY，所以 `ls` 有颜色、`python` 交互正常。

---

## macOS

```bash
python3 -m jiaozi --open
```

终端走 PTY，和 Linux 一致。没有 systemd，想开机自启可以用 `launchd`：

```xml
<!-- ~/Library/LaunchAgents/cn.jiaozi.aiworld.plist -->
<key>ProgramArguments</key>
<array>
  <string>/usr/bin/python3</string><string>-m</string><string>jiaozi</string>
  <string>--host</string><string>127.0.0.1</string>
</array>
<key>RunAtLoad</key><true/>
```

---

## Windows（开发预览）

```powershell
python -m jiaozi --open
```

能跑，但有两条限制：
1. 终端走**管道**而不是 PTY，没有 job control（提示符是 `bash-5.3$` 而不是完整 PS1），
   `vim`/`top` 这类交互程序不可用。
2. 若装了 Git for Windows，会自动用它的 `bash.exe`；否则退回 `cmd.exe`。

生产环境请用 Linux。

---

## 反向代理（可选）

想让手机通过 HTTPS 访问，用 Caddy 一行：

```
aiworld.example.com {
    reverse_proxy 127.0.0.1:8787 {
        flush_interval -1      # 关键：SSE 不能被缓冲
    }
}
```

nginx 对应的是 `proxy_buffering off;` 和 `proxy_read_timeout 3600s;`。
注意：一旦暴露到公网，请同时改 token，并考虑加一层 basic auth——本项目的鉴权很轻。

---

## 卸载

```bash
rm -rf ~/.jiaozi                                   # 配置、会话、回收站
rm ~/.local/bin/jiaozi ~/.local/bin/jiaozi-kiosk   # 启动器
rm ~/.local/share/applications/jiaozi-aiworld.desktop
sudo systemctl disable --now jiaozi && sudo rm /etc/systemd/system/jiaozi.service
```
