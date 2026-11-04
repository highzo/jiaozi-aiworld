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
   `vim`/`top` 这类交互程序不可用。界面上会明确标一行黄字说明。
2. 若装了 Git for Windows，会自动用它的 `bash.exe`；否则退回 `cmd.exe`。

**注意端口独占**：Windows 的 `SO_REUSEADDR` 允许两个进程同时监听同一端口。
本项目已经显式关掉它（改用 `SO_EXCLUSIVEADDRUSE`），所以重复启动会明确报错，
而不是让两个实例抢请求。如果看到"端口已被占用"：

```powershell
Get-NetTCPConnection -LocalPort 8787 -State Listen | Select-Object OwningProcess
```

生产环境请用 Linux。

## WSL2（在 Windows 里跑完整 Linux）

这是 Windows 上**推荐**的方式：拿到真 PTY、真文件系统、真 systemd（WSL2 已支持）。

```powershell
# 1. 在管理员 PowerShell 里装 WSL（装完要重启一次）
wsl --install -d Ubuntu

# 2. 进 Ubuntu
wsl -d Ubuntu

# 3. 里面就是普通 Linux，照 Linux 那节来
sudo apt update && sudo apt install -y python3
git clone <本项目地址> && cd jiaozi-aiworld
python3 -m jiaozi --host 0.0.0.0 --port 8787
```

Windows 侧直接开 `http://localhost:8787/` 就能用——WSL2 会把端口自动转发到 localhost。
手机走局域网访问时，WSL2 的 IP 和 Windows 不同，需要一条端口转发（管理员 PowerShell）：

```powershell
$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
netsh interface portproxy add v4tov4 listenport=8787 listenaddress=0.0.0.0 `
  connectport=8787 connectaddress=$wslIp
New-NetFirewallRule -DisplayName "JiaoziAI 8787" -Direction Inbound `
  -LocalPort 8787 -Protocol TCP -Action Allow
```

**为什么 WSL 比原生 Windows 好**：终端拿到的是真 PTY，`top`、`vim`、`htop` 全部正常，
和安卓/树莓派上的行为完全一致——也就是你能在 Windows 上把要给机器人的东西先调通。

### 实测记录（Ubuntu 24.04.5 LTS / WSL2，已验证）

这个组合是**真跑通过**的，不是推测：服务整个跑在 Linux VM 里，Windows 侧用浏览器访问，
冒烟 57 项 + 界面 40 项 + VT 24 项全绿。环境实测值：

| 项 | 值 |
|---|---|
| 发行版 | Ubuntu 24.04.5 LTS，`ext4.vhdx` 约 1.3 GB |
| VM | WSL2，`Linux 5.10.16.3-microsoft-standard-WSL2`，x86_64 |
| Python | 系统自带 3.12.3，**零第三方依赖，不用 pip install** |
| 宿主网卡 | `vEthernet (WSL)` = `172.28.128.1`（NAT 模式下的主机地址） |
| 转发 | 8787 的监听者是 `wslhost.exe`，即 WSL2 自动做 localhost 转发 |

**在 WSL 里跑起来**：

```bash
cd ~/jiaozi-aiworld
python3 -m jiaozi --host 0.0.0.0 --port 8787
```

然后 Windows 侧直接开 `http://127.0.0.1:8787/`，不需要任何端口转发。

**从 Windows 侧对 WSL 实例跑测试**（跨机器验证，三个变量必须显式给）：

```bash
JIAOZI_URL=http://127.0.0.1:8787 \
MOCK_BIND=0.0.0.0 \
JIAOZI_MOCK_URL=http://172.28.128.1:8799/v1 \
JIAOZI_TOKEN=<WSL 里 ~/.jiaozi/config.json 的 auth.token> \
python tests/smoke_test.py
```

三个变量各自解决一个错位，缺一个就会有一片断言假红：

- `JIAOZI_TOKEN` —— 否则读到的是 Windows 的 token，服务端不认
- `MOCK_BIND=0.0.0.0` —— 否则假模型只监听 Windows 回环，Linux 侧连不进来
- `JIAOZI_MOCK_URL` —— 必须给 Linux 视角能到达的主机地址（NAT 模式下是 `172.28.128.1`）

想验证连通性，最省事的办法是让 Linux 里的服务自己去连一次：
`POST /api/llm/test` 带上 `{"base_url": "http://172.28.128.1:8799/v1"}`，
能返回模型列表就说明这条路通了。

**文件管理器只看得到 `/root`**，这是沙箱的默认根目录，不是 bug。
想让它能进 `/mnt/c`（就是你的 Windows C 盘）或者整盘，在
`设置 → 文件 → 根目录` 里加一条 `/mnt` 或 `/` 即可——加几个就多看到几个入口，
沙箱边界也随之放宽，自己按需要来。


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
