#!/usr/bin/env bash
# 饺子AIWorld · 安卓（Termux）部署
# 不需要 root。核心只依赖 Python 标准库，所以 Termux 里直接跑，无需 proot。
#
# 用法（在手机上打开 Termux 后）：
#   1) 把整个 jiaozi-aiworld 目录传到手机（adb push / 文件管理器 / git clone）
#   2) bash scripts/android-termux.sh /path/to/jiaozi-aiworld
#   3) 浏览器打开提示的地址，加到主屏幕即可全屏使用
set -euo pipefail

ROOT="${1:-$(pwd)}"
PORT="${JIAOZI_PORT:-8787}"

say() { printf '\033[1;36m▸\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*"; exit 1; }

command -v pkg >/dev/null 2>&1 || die "这看起来不是 Termux。安卓请用 Termux（F-Droid 版）。"

say "安装依赖（python + 存储权限 + 唤醒锁）"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python termux-api >/dev/null 2>&1 || pkg install -y python >/dev/null

say "申请共享存储权限（会让你点一次允许）"
command -v termux-setup-storage >/dev/null 2>&1 && termux-setup-storage || true

[ -d "$ROOT/jiaozi" ] || die "目录不对：$ROOT （应包含 jiaozi/ 子目录）"

say "启动"
cd "$ROOT"
# 允许访问手机存储；把 /sdcard 作为第二个沙箱根目录
python3 - <<'PY'
import sys, os
sys.path.insert(0, ".")
from jiaozi import config
roots = ["~"]
for p in ("/sdcard", "/storage/emulated/0"):
    if os.path.isdir(p):
        roots.append(p)
        break
config.save({"fs": {"roots": roots}, "server": {"host": "0.0.0.0"}})
print("  沙箱:", config.sandbox_roots())
PY

# 防止息屏后被系统杀掉
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

echo
echo "────────────────────────────────────────────"
echo " 手机上打开浏览器访问： http://127.0.0.1:$PORT/"
echo " 同一 WiFi 的电脑可以访问： 看下面打印的局域网地址"
echo " 建议：浏览器菜单 → 添加到主屏幕，即可全屏像 App 一样用"
echo " 停止：Ctrl+C（或 termux-wake-unlock 释放唤醒锁）"
echo "────────────────────────────────────────────"
echo

python3 -m jiaozi --host 0.0.0.0 --port "$PORT"
