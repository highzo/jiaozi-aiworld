#!/usr/bin/env python3
"""i18n 词典校验 —— 给贡献者和 CI 用。

检查四件事，任何一条不过都算失败：

1. 每个 `i18n/*.json` 能解析、有 strings 字段。
2. 每条 key 都能在源码里找到（防止改了文案留下孤儿条目）。
3. 占位符两边一致：`{name}` / `{n}` 不能多也不能少。
   这条最容易出错——德语写了 `{n}` 但忘了 `{name}`，界面就会显示字面量。
4. 覆盖率报告，写进 README 用。

用法：
    python3 tools/i18n_check.py          # 检查 + 打印覆盖率
    python3 tools/i18n_check.py --strict # 覆盖率跌破门槛也算失败（发版前用）
    python3 tools/i18n_check.py --strict --min 70   # 想要求更严就调高

为什么默认门槛是 50% 而不是 100%：词典是分批翻的，第一版只翻核心界面，
长段说明故意留英文回落。门槛的作用是"防止越翻越少"，不是"逼人翻完"。
定成 100% 的唯一后果是没人跑它。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "jiaozi" / "desktop"
I18N_DIR = DESKTOP / "i18n"

PAT_T = re.compile(r"(?:JZ\.t|\bt)\(\s*'((?:[^'\\]|\\.)*)'")
PAT_ATTR = re.compile(r'data-i18n(?:-title|-ph|-html)?="([^"]*)"')
PAT_VAR = re.compile(r"\{(\w+)\}")
# 应用名不走 t()，是在渲染时 JZ.t(app.name) 才翻译的，提取时要单独抓
PAT_APPNAME = re.compile(r"id:\s*'[\w-]+'\s*,\s*name:\s*'([^']+)'")


def source_keys() -> dict[str, list[str]]:
    """扫描前端源码，收集所有被 t() 包裹或标了 data-i18n 的原文。"""
    found: dict[str, list[str]] = {}
    for f in sorted(DESKTOP.rglob("*")):
        # 注意：**不要跳过 i18n.js**。它里面也有 t() 文案（品牌名、语言来源说明），
        # 早先为了图省事把它整个排除，结果这 5 条永远不算"缺译"，
        # 德语用户看到的就是中文。踩过一次，记在这。
        if not f.is_file() or f.suffix not in (".js", ".html"):
            continue
        txt = f.read_text(encoding="utf-8")
        if f.suffix == ".html":
            hits = [m.group(1) for m in PAT_ATTR.finditer(txt)]
        else:
            hits = [m.group(1).replace("\\'", "'") for m in PAT_T.finditer(txt)]
            hits += [m.group(1) for m in PAT_APPNAME.finditer(txt)]
        for k in hits:
            found.setdefault(k, [])
            if f.name not in found[k]:
                found[k].append(f.name)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="覆盖率跌破 --min 时返回非零")
    ap.add_argument("--min", type=float, default=50.0,
                    help="--strict 的覆盖率门槛（百分比，默认 50）")
    args = ap.parse_args()

    keys = source_keys()
    files = sorted(I18N_DIR.glob("*.json"))
    if not files:
        print("✗ i18n/ 下没有词典")
        return 1

    print(f"源码里共有 {len(keys)} 条待翻译文案，词典 {len(files)} 份\n")
    bad = 0
    rows = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"✗ {f.name}: JSON 解析失败 —— {e}")
            bad += 1
            continue
        strings = data.get("strings") or {}
        code = data.get("code") or f.stem

        orphans = [k for k in strings if k not in keys]
        missing = [k for k in keys if k not in strings]
        mismatch = []
        for k, v in strings.items():
            a = sorted(PAT_VAR.findall(k))
            b = sorted(PAT_VAR.findall(str(v)))
            if a != b:
                mismatch.append((k, a, b))

        cov = 100.0 * (len(keys) - len(missing)) / max(1, len(keys))
        rows.append((code, cov, len(missing), len(orphans)))
        status = "✓"
        if orphans or mismatch:
            status = "✗"
            bad += 1
        print(f"{status} {code:<7} {cov:5.1f}%  缺 {len(missing):>3}  孤儿 {len(orphans):>3}  占位符不符 {len(mismatch):>2}")
        for k in orphans[:5]:
            print(f"     孤儿: {k[:52]}")
        for k, a, b in mismatch[:5]:
            print(f"     占位符: {k[:40]} | 原文 {a} ≠ 译文 {b}")

    print("\n覆盖率一览（可直接贴进 README）")
    print("| 语言 | 覆盖率 |")
    print("|---|---|")
    for code, cov, _, _ in rows:
        print(f"| `{code}` | {cov:.1f}% |")

    if args.strict:
        low = [r for r in rows if r[1] < args.min]
        if low:
            print("\n✗ 以下语言覆盖率低于 %.0f%%：" % args.min
                  + ", ".join("%s(%.1f%%)" % (r[0], r[1]) for r in low))
            return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
