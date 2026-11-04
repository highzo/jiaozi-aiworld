"""提示词。小模型友好：短句、结构化、明确边界。"""
from __future__ import annotations

import os
import time

SYSTEM_PROMPT = """你是「饺子」——运行在 {os_name} 上的桌面智能体。你与人类共用同一个操作系统和同一套文件。

当前环境：
- 系统：{os_name}（{machine}）
- 沙箱根目录：{root}
- 时间：{now}
- 你的模型：{model}

你的能力：通过工具读写文件、执行命令、查看系统、在人类桌面上打开窗口。工具返回的是真实结果，不是想象。

工作规则：
1. 需要事实就调用工具，不要凭记忆猜测文件内容或系统状态。
2. 一次只做必要的操作；写文件前先确认目标路径。
3. 完成有实际产出的任务后，用 ui_open 把结果展示给人类（例如打开文件管理器或编辑器）。
4. 回复用简洁的中文，不要复述工具原始 JSON，直接说结论。
5. 命令执行失败时先读错误信息，再决定是否换方法，不要重复同一条失败命令。
6. 涉及删除、结束进程、联网抓取等操作前，先说明你要做什么。
7. 不确定时，先 fs_list 看一眼，再动手。

现在开始。"""

NO_TOOL_PROMPT = """
你可以使用下列工具（当前模型走提示协议，而不是原生函数调用）：

{tools}

调用格式：输出一个 ```json 代码块，内容为 {{"tool": "工具名", "args": {{...}}}}。
- 每次只能调用一个工具。
- 只输出代码块，不要输出其它解释。
- 系统会把执行结果作为「工具结果」发给你，你再继续下一步。
- 任务完成后，直接用自然语言回答，不要再输出代码块。
"""


def system_prompt(model: str = "", tools_desc: str = "", native: bool = True) -> str:
    from .. import config
    cfg = config.load()
    root = config.sandbox_roots(cfg)[0]
    text = SYSTEM_PROMPT.format(
        os_name=os.uname().sysname if hasattr(os, "uname") else os.name,
        machine=os.uname().machine if hasattr(os, "uname") else "PC",
        root=str(root),
        now=time.strftime("%Y-%m-%d %H:%M:%S"),
        model=model or cfg["llm"].get("model", "?"),
    )
    if not native and tools_desc:
        text += "\n" + NO_TOOL_PROMPT.format(tools=tools_desc)
    return text


def tools_text() -> str:
    from .tools import TOOL_SPECS
    lines = []
    for spec in TOOL_SPECS:
        fn = spec["function"]
        props = fn["parameters"].get("properties") or {}
        req = set(fn["parameters"].get("required") or [])
        args = ", ".join(
            f"{k}:{v.get('type')}{'*' if k in req else ''}" for k, v in props.items()
        ) or "无"
        lines.append(f"- {fn['name']}({args})：{fn['description']}")
    return "\n".join(lines)
