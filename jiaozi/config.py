"""饺子AIWorld · 配置与运行时路径

零第三方依赖。所有可写数据放在 ~/.jiaozi（或 $JIAOZI_HOME）。
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import socket
import threading
from pathlib import Path

APP_NAME = "饺子AIWorld"
APP_ID = "jiaozi-aiworld"
VERSION = "0.1.0"


def data_dir() -> Path:
    env = os.environ.get("JIAOZI_HOME")
    p = Path(env).expanduser() if env else Path.home() / ".jiaozi"
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA_DIR = data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_DIR = DATA_DIR / "sessions"
TRASH_DIR = DATA_DIR / "trash"
UPLOAD_DIR = DATA_DIR / "uploads"
LOG_DIR = DATA_DIR / "logs"
for _d in (HISTORY_DIR, TRASH_DIR, UPLOAD_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

#: 项目根目录（包含 jiaozi/ 与 desktop/）
ROOT = Path(__file__).resolve().parent.parent
DESKTOP_DIR = ROOT / "jiaozi" / "desktop"

DEFAULTS: dict = {
    "server": {
        "host": "127.0.0.1",
        "port": 8787,
        #: 局域网访问需要 token；本机回环默认放行，体验更顺
        "allow_localhost": True,
    },
    "auth": {
        "token": "",
    },
    "fs": {
        #: 允许访问的根目录白名单，~ 会被展开
        "roots": ["~"],
        "max_read_bytes": 4 * 1024 * 1024,
        "max_upload_bytes": 64 * 1024 * 1024,
    },
    "llm": {
        #: 任何 OpenAI 兼容端点：Ollama / llama.cpp / vLLM / LM Studio / DeepSeek ...
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:1.5b-instruct",
        "api_key": "",
        "temperature": 0.3,
        "max_tokens": 1024,
        "timeout": 180,
        #: 小模型的 function-calling 支持通常不完整，可关掉走提示协议
        "native_tools": True,
        #: 关闭流式可降低部分老设备的兼容问题
        "stream": True,
    },
    "image": {
        #: 文生图。留空 base_url/api_key 就复用 llm 的（Agnes/OpenAI/兼容端点都走同一套 /images/generations）
        "enabled": True,
        "base_url": "",
        "api_key": "",
        "model": "agnes-image-2.5-flash",
        "size": "1024x1024",
        "timeout": 240,
        #: 出图存哪。必须在 fs.roots 白名单内，否则 AI 生成完自己也打不开
        "save_dir": "~/Pictures/JiaoziAI",
    },
    "agent": {
        "max_steps": 12,
        #: always=每次工具调用都要人确认；auto=仅危险操作需确认；never=全自动
        "approval": "auto",
        "shell_timeout": 60,
        "max_output": 8000,
    },
    "ui": {
        "theme": "light",
        "wallpaper": "aurora",
        "accent": "#2f6bff",
        "language": "zh",
    },
    "shell": {
        "default": "",
    },
    "device": {
        #: 给机器人/外部设备调用的简单任务接口开关
        "enabled": True,
    },
}


_lock = threading.RLock()
_cache: dict | None = None


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(reload: bool = False) -> dict:
    """读取配置；缺失字段用默认值补齐并回写。"""
    global _cache
    with _lock:
        if _cache is not None and not reload:
            return _cache
        raw: dict = {}
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text("utf-8"))
            except Exception:
                raw = {}
        cfg = _deep_merge(DEFAULTS, raw)
        changed = False
        if not cfg["auth"].get("token"):
            cfg["auth"]["token"] = secrets.token_urlsafe(18)
            changed = True
        if changed or not CONFIG_PATH.exists() or raw != cfg:
            _write(cfg)
        _cache = cfg
        return cfg


def _write(cfg: dict) -> None:
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(CONFIG_PATH)


def _strip_masked(patch: dict) -> dict:
    """丢掉前端回传的脱敏占位密钥。

    public_view() 把 api_key 变成 ********；如果前端不慎把它原样提交回来，
    真实密钥就会被星号覆盖，之后所有请求 401。这里做最后一道防线：
    空值和纯星号一律视为「不修改」。
    """
    out = copy.deepcopy(patch or {})
    for sec in ("llm", "image"):
        d = out.get(sec)
        if isinstance(d, dict) and "api_key" in d:
            v = str(d.get("api_key") or "").strip()
            if not v or set(v) == {"*"}:
                d.pop("api_key", None)
    return out


def save(patch: dict) -> dict:
    """局部更新配置并立即生效。"""
    global _cache
    with _lock:
        cur = load()
        cfg = _deep_merge(cur, _strip_masked(patch))
        _write(cfg)
        _cache = cfg
        return cfg


def public_view(cfg: dict | None = None) -> dict:
    """给前端看的配置：不返回 token 与 api_key 明文。"""
    cfg = copy.deepcopy(cfg or load())
    token = cfg["auth"].pop("token", "")
    cfg["auth"]["has_token"] = bool(token)
    key = cfg["llm"].get("api_key") or ""
    cfg["llm"]["api_key_set"] = bool(key)
    cfg["llm"]["api_key"] = ("*" * 8) if key else ""
    ikey = cfg["image"].get("api_key") or ""
    cfg["image"]["api_key_set"] = bool(ikey)
    cfg["image"]["api_key"] = ("*" * 8) if ikey else ""
    cfg["_meta"] = {
        "version": VERSION,
        "name": APP_NAME,
        "platform": os.name,
        "data_dir": str(DATA_DIR),
        "python": os.sys.version.split()[0],
        "hostname": socket.gethostname(),
    }
    return cfg


def sandbox_roots(cfg: dict | None = None) -> list[Path]:
    cfg = cfg or load()
    out: list[Path] = []
    for r in cfg["fs"].get("roots") or []:
        try:
            p = Path(os.path.expandvars(os.path.expanduser(str(r)))).resolve()
        except Exception:
            continue
        if p.exists():
            out.append(p)
    if not out:
        out = [Path.home().resolve()]
    return out


def default_shell() -> str:
    cfg = load()
    s = (cfg["shell"].get("default") or "").strip()
    if s:
        return s
    if os.name == "posix":
        for c in (os.environ.get("SHELL"), "/bin/bash", "/bin/sh"):
            if c and Path(c).exists():
                return c
        return "/bin/sh"
    # Windows 仅作为开发/演示环境
    import shutil

    found = shutil.which("bash")
    if found:
        return found
    for c in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
        os.path.expanduser(r"~\.workbuddy\binaries\PortableGit\versions\1.3.0\bin\bash.exe"),
    ):
        if Path(c).exists():
            return c
    return "cmd.exe"
