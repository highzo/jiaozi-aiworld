"""命令行入口：python3 -m jiaozi"""
from __future__ import annotations

import argparse
import os
import sys

from . import config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="jiaozi",
        description="饺子AIWorld —— 人机共用的桌面层，可在 PC / 安卓 / 开发板运行")
    ap.add_argument("--host", default="", help="监听地址，局域网共享用 0.0.0.0")
    ap.add_argument("--port", type=int, default=0, help="端口，默认 8787")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--token", default="", help="临时指定访问 token")
    ap.add_argument("--config", action="store_true", help="打印配置路径与内容")
    ap.add_argument("--reset-token", action="store_true", help="重置访问 token")
    ap.add_argument("--version", action="store_true", help="显示版本")
    args = ap.parse_args(argv)

    if args.version:
        print(f"{config.APP_NAME} {config.VERSION}")
        return 0

    cfg = config.load()
    if args.reset_token:
        import secrets
        config.save({"auth": {"token": secrets.token_urlsafe(18)}})
        cfg = config.load()
        print("新 token:", cfg["auth"]["token"])
    if args.token:
        config.save({"auth": {"token": args.token}})

    if args.config:
        print("配置文件:", config.CONFIG_PATH)
        import json
        print(json.dumps(config.public_view(), ensure_ascii=False, indent=2))
        return 0

    os.environ.setdefault("JIAOZI_HOST", args.host or cfg["server"]["host"])
    from .server import serve
    serve(args.host, args.port, args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
