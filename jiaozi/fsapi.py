"""沙箱内文件系统操作。AI 与人类走同一套 API —— 这是"人机共用一份桌面"的技术基础。"""
from __future__ import annotations

import base64
import mimetypes
import os
import shutil
import time
from pathlib import Path

from . import config

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html",
    ".htm", ".css", ".scss", ".sh", ".bash", ".zsh", ".fish", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".rs", ".go", ".java", ".kt", ".swift", ".rb", ".php", ".lua",
    ".sql", ".csv", ".tsv", ".log", ".env", ".gitignore", ".dockerfile", ".xml",
    ".svg", ".vue", ".svelte", ".r", ".m", ".pl", ".asm", ".s", ".txt", ".tex",
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"}


class FSError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def resolve(path: str | None, *, must_exist: bool = False) -> Path:
    """把用户/AI 给的路径解析成绝对路径，并强制落在沙箱根目录内。"""
    cfg = config.load()
    roots = config.sandbox_roots(cfg)
    raw = (path or "").strip()
    if raw in ("", "~", "/"):
        # 空路径 = 沙箱第一个根；"/" 特殊处理为根列表
        if raw == "/":
            return roots[0]
        raw = str(roots[0])
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():
        p = roots[0] / p
    try:
        p = p.resolve()
    except OSError as e:
        raise FSError(f"路径无法解析: {e}") from e

    for r in roots:
        try:
            if p == r or r in p.parents:
                if must_exist and not p.exists():
                    raise FSError(f"路径不存在: {p}", 404)
                return p
        except OSError:
            continue
    raise FSError(f"越界访问被拒绝（不在沙箱根目录内）: {p}", 403)


def roots_view() -> list[dict]:
    out = []
    for r in config.sandbox_roots():
        out.append({"name": r.name or str(r), "path": str(r)})
    return out


def kind_of(p: Path) -> str:
    if p.is_dir():
        return "dir"
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return "binary"


def stat_entry(p: Path) -> dict:
    try:
        st = p.stat()
    except OSError as e:
        raise FSError(str(e), 404) from e
    return {
        "name": p.name or str(p),
        "path": str(p),
        "kind": kind_of(p),
        "is_dir": p.is_dir(),
        "size": 0 if p.is_dir() else st.st_size,
        "mtime": st.st_mtime,
        "mode": oct(st.st_mode & 0o777),
    }


def list_dir(path: str | None, show_hidden: bool = True) -> dict:
    p = resolve(path, must_exist=True)
    if not p.is_dir():
        raise FSError("不是目录")
    items: list[dict] = []
    try:
        with os.scandir(p) as it:
            for e in it:
                if not show_hidden and e.name.startswith("."):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                    is_dir = e.is_dir(follow_symlinks=False)
                    fp = Path(e.path)
                    items.append({
                        "name": e.name,
                        "path": str(fp),
                        "kind": "dir" if is_dir else kind_of(fp),
                        "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size,
                        "mtime": st.st_mtime,
                        "hidden": e.name.startswith("."),
                    })
                except OSError:
                    continue
    except PermissionError as e:
        raise FSError(f"没有读取权限: {p}", 403) from e
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = str(p.parent) if any(p != r for r in config.sandbox_roots()) else None
    return {"path": str(p), "parent": parent, "items": items, "roots": roots_view()}


def read_text(path: str, max_bytes: int | None = None) -> dict:
    p = resolve(path, must_exist=True)
    cfg = config.load()
    limit = max_bytes or int(cfg["fs"]["max_read_bytes"])
    if p.is_dir():
        raise FSError("是目录，无法读取为文本")
    size = p.stat().st_size
    with open(p, "rb") as f:
        raw = f.read(limit + 1)
    truncated = len(raw) > limit
    raw = raw[:limit]
    try:
        text = raw.decode("utf-8")
        enc = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "replace")
        enc = "utf-8(replace)"
    return {"path": str(p), "text": text, "size": size, "truncated": truncated,
            "encoding": enc, "binary": b"\x00" in raw[:4096]}


def read_bytes(path: str) -> tuple[bytes, str]:
    p = resolve(path, must_exist=True)
    if p.is_dir():
        raise FSError("是目录")
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return p.read_bytes(), ctype


def write_text(path: str, text: str, *, mkdirs: bool = True) -> dict:
    p = resolve(path)
    if p.is_dir():
        raise FSError("目标是目录")
    if mkdirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".jztmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(p)
    return {"path": str(p), "size": p.stat().st_size}


def save_upload(dir_path: str, name: str, b64: str) -> dict:
    cfg = config.load()
    raw = base64.b64decode(b64.split(",")[-1])
    if len(raw) > int(cfg["fs"]["max_upload_bytes"]):
        raise FSError("文件过大", 413)
    d = resolve(dir_path)
    if not d.is_dir():
        raise FSError("目标不是目录")
    safe = Path(name).name or "upload.bin"
    p = d / safe
    n = 1
    while p.exists():
        p = d / f"{Path(safe).stem}-{n}{Path(safe).suffix}"
        n += 1
    p.write_bytes(raw)
    return stat_entry(p)


def mkdir(path: str) -> dict:
    p = resolve(path)
    p.mkdir(parents=True, exist_ok=False)
    return stat_entry(p)


def move(src: str, dst: str) -> dict:
    a = resolve(src, must_exist=True)
    b = resolve(dst)
    if b.is_dir():
        b = b / a.name
    b.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(a), str(b))
    return stat_entry(b)


def copy(src: str, dst: str) -> dict:
    a = resolve(src, must_exist=True)
    b = resolve(dst)
    if b.is_dir():
        b = b / a.name
    if b.exists():
        b = b.with_name(f"{b.stem}-copy{b.suffix}")
    b.parent.mkdir(parents=True, exist_ok=True)
    if a.is_dir():
        shutil.copytree(a, b)
    else:
        shutil.copy2(a, b)
    return stat_entry(b)


def delete(path: str, hard: bool = False) -> dict:
    p = resolve(path, must_exist=True)
    if any(p == r for r in config.sandbox_roots()):
        raise FSError("不允许删除沙箱根目录", 403)
    if hard:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"path": str(p), "trashed": False}
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = config.TRASH_DIR / f"{ts}-{p.name}"
    try:
        shutil.move(str(p), str(dest))
    except Exception:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"path": str(p), "trashed": False}
    return {"path": str(p), "trashed": True, "trash_path": str(dest)}


def search(root: str, query: str, limit: int = 200, max_depth: int = 6) -> list[dict]:
    base = resolve(root, must_exist=True)
    q = (query or "").lower()
    out: list[dict] = []
    if not q:
        return out
    base_depth = len(base.parts)
    t0 = time.time()
    for dirpath, dirnames, filenames in os.walk(base):
        if time.time() - t0 > 8:
            break
        depth = len(Path(dirpath).parts) - base_depth
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".git") and d != "node_modules"]
        for name in dirnames + filenames:
            if q in name.lower():
                fp = Path(dirpath) / name
                try:
                    st = fp.stat()
                except OSError:
                    continue
                out.append({"name": name, "path": str(fp),
                            "is_dir": fp.is_dir(), "size": st.st_size,
                            "mtime": st.st_mtime})
                if len(out) >= limit:
                    return out
    return out


def disk_usage(path: str | None = None) -> dict:
    p = resolve(path) if path else config.sandbox_roots()[0]
    try:
        u = shutil.disk_usage(str(p))
        return {"total": u.total, "used": u.used, "free": u.free}
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


def ensure_dir(path: str) -> Path:
    p = resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
