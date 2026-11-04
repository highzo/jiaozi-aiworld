"""文生图：把 OpenAI 兼容的 /images/generations 变成 Agent 的一只手。

为什么放在后端而不是前端：
机器人上没有浏览器，图片必须落成磁盘上的真实文件，
人类（文件管理器 / 图片查看器）和 AI（fs_list / fs_read）才能用同一套东西打开它。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config, fsapi
from .llm import _LOCAL_HOSTS

#: 单张图下载上限，防止远端返回一个巨大文件把开发板塞满
MAX_BYTES = 24 * 1024 * 1024

_SAFE = re.compile(r"[^\w\u4e00-\u9fff-]+")


class ImageError(Exception):
    def __init__(self, msg: str, status: int = 0, raw: str = ""):
        super().__init__(msg)
        self.status = status
        self.raw = raw


def _cfg(cfg: dict | None = None) -> dict:
    """图像配置；base_url / api_key / model 留空则回落到 llm 的。"""
    c = cfg or config.load()
    img = dict(c["image"])
    llm = c["llm"]
    if not img.get("base_url"):
        img["base_url"] = llm.get("base_url") or ""
    if not img.get("api_key"):
        img["api_key"] = llm.get("api_key") or ""
    if not img.get("model"):
        img["model"] = llm.get("model") or "agnes-image-2.5-flash"
    if not img.get("size"):
        img["size"] = "1024x1024"
    return img


def _url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        raise ImageError("未配置图像接口地址（image.base_url 或 llm.base_url）")
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    return base + path


def _opener(base: str):
    """本机/局域网直连绕代理；公网网关走系统代理（国内办公网通常必须）。"""
    host = urllib.parse.urlparse(base).hostname or ""
    if _LOCAL_HOSTS.match(host):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _post(base: str, payload: dict, timeout: float) -> dict:
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    key = payload.pop("__key", "")
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        _url(base, "/images/generations"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=hdrs, method="POST")
    try:
        with _opener(base).open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise ImageError(f"图像接口返回 {e.code}", e.code, detail) from e
    except urllib.error.URLError as e:
        raise ImageError(f"连不上图像接口：{e.reason}") from e
    except (TimeoutError, ValueError) as e:
        raise ImageError(f"图像接口请求失败：{e}") from e


def _download(url: str, timeout: float) -> tuple[bytes, str]:
    try:
        with urllib.request.build_opener().open(url, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
            ctype = r.headers.get("Content-Type", "") or ""
    except Exception as e:
        raise ImageError(f"下载生成结果失败：{e}") from e
    if len(data) > MAX_BYTES:
        raise ImageError("生成结果超过 24MB，已放弃保存")
    return data, ctype


def _ext(ctype: str, url: str) -> str:
    ctype = (ctype or "").lower()
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "webp" in ctype:
        return ".webp"
    if "gif" in ctype:
        return ".gif"
    path = urllib.parse.urlparse(url).path.lower()
    for e in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if path.endswith(e):
            return ".png" if e == ".jpeg" else e
    return ".png"


def _slug(text: str, limit: int = 28) -> str:
    s = _SAFE.sub("-", (text or "").strip())[:limit].strip("-")
    return s or "image"


def _target_dir(img: dict) -> Path:
    raw = img.get("save_dir") or "~/Pictures/JiaoziAI"
    p = fsapi.resolve(os.path.expanduser(str(raw)))
    # 必须落在沙箱内，否则 AI 生成的图自己都列不出来
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate(prompt: str, n: int = 1, size: str = "", model: str = "",
             cfg: dict | None = None) -> dict:
    """生成 n 张图并保存到磁盘，返回文件绝对路径列表。"""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageError("提示词不能为空")
    img = _cfg(cfg)
    if not img.get("enabled", True):
        raise ImageError("图像生成已在设置里关闭")

    n = max(1, min(int(n or 1), 4))
    size = (size or img["size"]).strip()
    model = (model or img["model"]).strip()
    base = img["base_url"]
    key = img.get("api_key") or ""
    timeout = float(img.get("timeout") or 240)

    out_dir = _target_dir(img)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    files: list[str] = []
    started = time.time()

    for i in range(n):
        payload: dict = {"model": model, "prompt": prompt, "n": 1, "__key": key}
        if size:
            payload["size"] = size
        data = _post(base, payload, timeout)
        items = data.get("data") or []
        if not items:
            raise ImageError("图像接口没有返回图片", 0, json.dumps(data)[:400])

        item = items[0]
        b64 = item.get("b64_json") or ""
        url = item.get("url") or ""
        if b64:
            raw = base64.b64decode(b64)
            ext = ".png"
        elif url:
            raw, ctype = _download(url, timeout)
            ext = _ext(ctype, url)
        else:
            raise ImageError("图像接口返回里既没有 url 也没有 b64_json",
                             0, json.dumps(item)[:300])

        suffix = "" if n == 1 else f"-{i + 1}"
        name = f"{stamp}-{_slug(prompt)}{suffix}{ext}"
        path = out_dir / name
        k = 1
        while path.exists():
            path = out_dir / f"{stamp}-{_slug(prompt)}{suffix}-{k}{ext}"
            k += 1
        path.write_bytes(raw)
        files.append(str(path))

    return {
        "files": files,
        "model": model,
        "size": size,
        "prompt": prompt,
        "elapsed": round(time.time() - started, 1),
    }


def test(cfg: dict | None = None) -> dict:
    """连通性自检：真的生成一张小图，能落盘才算通。"""
    return generate("a small blue circle on white background, flat icon", n=1,
                    size="512x512", cfg=cfg)
