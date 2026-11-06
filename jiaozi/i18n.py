"""饺子AIWorld · 语言表与语言解析

三层解析顺序，越靠前越尊重用户本人：

1. **用户显式选过的**（`ui.language`，存在配置里）—— 一旦选过就永不被自动逻辑覆盖。
2. **浏览器/系统的 Accept-Language** —— 这是用户在自己设备上的真实偏好，
   比 IP 更准（一个在德国的中文用户，系统语言是中文，IP 说是德国）。
3. **IP 归属地** —— 首次访问、且浏览器语言不在支持列表里时兜底。

解析结果里带 source，前端据此显示"自动（按 IP 定为 xx）"，让用户知道
这个语言是谁决定的，而不是莫名其妙变了。
"""
from __future__ import annotations

#: code, 该语言自己的写法, 英文名, 国家/地区emoji（界面上帮助识别，不涉及政治含义）
LANGS: list[dict] = [
    {"code": "zh-CN", "native": "简体中文", "en": "Chinese (Simplified)", "region": "CN"},
    {"code": "zh-TW", "native": "繁體中文", "en": "Chinese (Traditional)", "region": "TW"},
    {"code": "en",    "native": "English",  "en": "English",   "region": "US"},
    {"code": "ja",    "native": "日本語",    "en": "Japanese",  "region": "JP"},
    {"code": "ko",    "native": "한국어",    "en": "Korean",    "region": "KR"},
    {"code": "de",    "native": "Deutsch",  "en": "German",    "region": "DE"},
    {"code": "fr",    "native": "Français", "en": "French",    "region": "FR"},
    {"code": "es",    "native": "Español",  "en": "Spanish",   "region": "ES"},
    {"code": "pt-BR", "native": "Português", "en": "Portuguese (Brazil)", "region": "BR"},
    {"code": "ru",    "native": "Русский",  "en": "Russian",   "region": "RU"},
]

CODES = [x["code"] for x in LANGS]
DEFAULT = "en"

#: 旧版本存的是 "zh"，做一次别名归一，避免升级后语言变回英文
_ALIASES = {
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "zh-hans-cn": "zh-CN",
    "zh-tw": "zh-TW", "zh-hant": "zh-TW", "zh-hk": "zh-TW", "zh-mo": "zh-TW",
    "en-us": "en", "en-gb": "en", "en-au": "en", "en-ca": "en",
    "ja-jp": "ja", "ko-kr": "ko", "de-de": "de", "fr-fr": "fr",
    "es-es": "es", "es-mx": "es", "es-419": "es",
    "pt": "pt-BR", "pt-br": "pt-BR", "pt-pt": "pt-BR",
    "ru-ru": "ru",
}

#: 国家/地区 → 语言。只收录有明确主要语言的地方，其余一律回落到英文。
COUNTRY_LANG = {
    "CN": "zh-CN", "TW": "zh-TW", "HK": "zh-TW", "MO": "zh-TW",
    "JP": "ja", "KR": "ko",
    "DE": "de", "AT": "de", "CH": "de", "LI": "de", "LU": "de",
    "FR": "fr", "MC": "fr", "BE": "fr", "SN": "fr", "CI": "fr", "CM": "fr",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es",
    "VE": "es", "UY": "es", "PY": "es", "BO": "es", "EC": "es", "CR": "es",
    "CU": "es", "DO": "es", "GT": "es", "HN": "es", "NI": "es", "PA": "es",
    "PR": "es", "SV": "es",
    "BR": "pt-BR", "PT": "pt-BR", "AO": "pt-BR", "MZ": "pt-BR",
    "RU": "ru", "BY": "ru", "KZ": "ru", "KG": "ru",
}


def normalize(code: str) -> str:
    """把任意写法收敛到支持列表里的一项；认不出来返回空串。"""
    c = str(code or "").strip()
    if not c:
        return ""
    low = c.lower().replace("_", "-")
    if low in _ALIASES:
        return _ALIASES[low]
    for x in CODES:
        if x.lower() == low:
            return x
    # zh-Hant-HK 这类：只取主语言再试一次
    base = low.split("-")[0]
    if base in _ALIASES:
        return _ALIASES[base]
    for x in CODES:
        if x.lower() == base:
            return x
    return ""


def from_accept_language(header: str) -> str:
    """按 q 值排序解析 Accept-Language，取第一个能支持的。"""
    if not header:
        return ""
    parts = []
    for i, token in enumerate(header.split(",")):
        bits = token.strip().split(";")
        tag = bits[0].strip()
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if tag and tag != "*":
            parts.append((-q, i, tag))
    for _, _, tag in sorted(parts):
        hit = normalize(tag)
        if hit:
            return hit
    return ""


def country_to_lang(cc: str) -> str:
    return COUNTRY_LANG.get(str(cc or "").upper(), "")


def resolve(cfg: dict, accept_language: str = "", country_code: str = "") -> dict:
    """决定这次请求用哪个语言，并说明理由。"""
    want = str((cfg.get("ui") or {}).get("language") or "auto")
    if want and want != "auto":
        hit = normalize(want)
        if hit:
            return {"lang": hit, "source": "user", "want": want}

    hit = from_accept_language(accept_language)
    if hit:
        return {"lang": hit, "source": "browser", "want": "auto"}

    hit = country_to_lang(country_code)
    if hit:
        return {"lang": hit, "source": "ip", "want": "auto", "country": country_code}

    return {"lang": DEFAULT, "source": "default", "want": "auto",
            "country": country_code or ""}


def public_list() -> list[dict]:
    return [dict(x) for x in LANGS]
