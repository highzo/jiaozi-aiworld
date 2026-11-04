#!/usr/bin/env bash
# 饺子AIWorld · Linux 一键安装（Debian/Ubuntu/Arch/Fedora/树莓派通用）
# 用法：
#   ./scripts/install.sh                # 安装启动器 + 桌面图标
#   ./scripts/install.sh --service      # 额外注册 systemd 开机自启
#   ./scripts/install.sh --kiosk        # 额外生成全屏 kiosk 启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${JIAOZI_PORT:-8787}"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
WANT_SERVICE=0
WANT_KIOSK=0
for a in "$@"; do
  case "$a" in
    --service) WANT_SERVICE=1 ;;
    --kiosk) WANT_KIOSK=1 ;;
    *) echo "未知参数: $a"; exit 1 ;;
  esac
done

say() { printf '\033[1;36m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*"; exit 1; }

say "检查 Python"
command -v python3 >/dev/null 2>&1 || die "没有 python3，请先安装：sudo apt install -y python3"
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
python3 - <<'PY' || die "Python 版本过低，需要 3.8+"
import sys
assert sys.version_info >= (3, 8), sys.version
PY
say "Python $PYV ✓  （本项目零第三方依赖，不需要 pip install）"

say "自检"
cd "$ROOT"
JIAOZI_QUIET=1 python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from jiaozi import config, fsapi, sysinfo
from jiaozi.shell import SHELLS
from jiaozi.agent import tools
cfg = config.load()
print("  沙箱根目录:", ", ".join(str(p) for p in config.sandbox_roots(cfg)))
print("  系统:", sysinfo.info()["os"], "| 工具数:", len(tools.TOOL_NAMES))
print("  配置文件:", config.CONFIG_PATH)
PY

say "写入启动器 $BIN_DIR/jiaozi"
mkdir -p "$BIN_DIR" "$APP_DIR"
cat > "$BIN_DIR/jiaozi" <<EOF
#!/usr/bin/env bash
cd "$ROOT" || exit 1
exec python3 -m jiaozi "\$@"
EOF
chmod +x "$BIN_DIR/jiaozi"

say "写入桌面图标"
ICON_PATH="$ROOT/jiaozi/desktop/icon.svg"
cat > "$APP_DIR/jiaozi-aiworld.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=饺子AIWorld
Name[en]=Jiaozi AIWorld
Comment=人和 AI 共用的桌面
Exec=$BIN_DIR/jiaozi --open
Icon=$ICON_PATH
Terminal=false
Categories=System;Utility;
StartupNotify=true
EOF
chmod +x "$APP_DIR/jiaozi-aiworld.desktop" 2>/dev/null || true

if [ "$WANT_KIOSK" = "1" ]; then
  say "生成 kiosk 全屏启动脚本"
  cat > "$BIN_DIR/jiaozi-kiosk" <<EOF
#!/usr/bin/env bash
# 全屏独占启动：适合开发板 / 一体机 / 机器人面板
cd "$ROOT" || exit 1
python3 -m jiaozi --host 127.0.0.1 --port $PORT &
SERVER=\$!
sleep 1.2
for B in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v \$B >/dev/null 2>&1; then
    exec \$B --kiosk --app=http://127.0.0.1:$PORT --noerrdialogs \\
      --disable-infobars --disable-session-crashed-bubble --incognito
  fi
done
echo "没有找到 Chromium/Chrome，请先安装：sudo apt install -y chromium"
kill \$SERVER 2>/dev/null
exit 1
EOF
  chmod +x "$BIN_DIR/jiaozi-kiosk"
fi

if [ "$WANT_SERVICE" = "1" ]; then
  say "注册 systemd 服务（需要 sudo）"
  sudo tee /etc/systemd/system/jiaozi.service >/dev/null <<EOF
[Unit]
Description=Jiaozi AIWorld desktop service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$ROOT
Environment=JIAOZI_HOME=$HOME/.jiaozi
ExecStart=/usr/bin/env python3 -m jiaozi --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now jiaozi.service
  say "服务已启动：systemctl status jiaozi"
fi

cat <<EOF

────────────────────────────────────────────
 安装完成。

 启动：      jiaozi --open
 或者：      cd "$ROOT" && python3 -m jiaozi --open

 只给本机用：  jiaozi
 局域网共享：  jiaozi --host 0.0.0.0
              （手机会得到一个带 token 的地址，直接打开就是同一个桌面）

 数据目录：    ~/.jiaozi   （配置、会话、回收站、日志）
 卸载：        rm ~/.local/bin/jiaozi ~/.local/share/applications/jiaozi-aiworld.desktop
────────────────────────────────────────────
EOF
