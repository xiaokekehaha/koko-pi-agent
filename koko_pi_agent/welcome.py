# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""启动欢迎卡片的纯渲染层。

对 `app.py` 零依赖：喂一个 `WelcomeContext` 和一个终端宽度，返回 Rich renderable。
布局选档、配色、tip 抽样都封在这里，外部无需知道。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal

from rich.style import Style
from rich.text import Text as RichText


# 像素画调色板：'.' 表示透明（不设任何颜色）。
PALETTE: dict[str, str] = {
    "o": "#D9843B",  # 柯基橘
    "w": "#F5F0E8",  # 奶白
    "k": "#2B2B2B",  # 眼睛与鼻子
}

# 每两行像素合成一行半块文字，所以行数必须是偶数。
MASCOT_LARGE: tuple[str, ...] = (
    "..oo..........oo..",
    ".oooo........oooo.",
    ".oooooooooooooooo.",
    ".ooowwwwwwwwwwooo.",
    ".oowkwwwwwwwwkwoo.",
    "..owwwwwwwwwwwwo..",
    "...wwwwwkkwwwww...",
    "....wwwwwwwwww....",
)

MASCOT_MINI: tuple[str, ...] = (
    "..oo..oo..",
    ".oooooooo.",
    ".owwwwwwo.",
    ".wkwwwwkw.",
    "..wwkkww..",
    "...wwww...",
)


McpKind = Literal["none", "connecting", "ready", "warning"]


@dataclass
class McpState:
    kind: McpKind = "none"
    server_count: int = 0
    tool_count: int = 0
    auth_needed: int = 0
    errors: tuple[str, ...] = ()


@dataclass
class WelcomeContext:
    app_name: str
    app_version: str
    model: str
    provider_name: str
    work_dir: str
    user_name: str | None = None
    is_returning: bool = False
    skills_count: int = 0
    agents_count: int = 0
    hooks_count: int = 0
    memory_entries: int = 0
    mcp: McpState = field(default_factory=McpState)
    # 测试注入固定 seed 让 tip 抽样可复现；None 表示用系统随机源。
    tips_seed: int | None = None


def render_pixels(rows: tuple[str, ...]) -> list[RichText]:
    """把像素行两两合成半块文字：前景色画上半格，背景色画下半格。

    透明格不设颜色——浅色终端上显式背景色会变成扎眼的黑块。
    像素行数为奇数时，最后一行按全透明补齐。
    """
    lines: list[RichText] = []
    for index in range(0, len(rows), 2):
        top = rows[index]
        bottom = rows[index + 1] if index + 1 < len(rows) else "." * len(top)
        line = RichText()
        for top_char, bottom_char in zip(top, bottom):
            top_color = PALETTE.get(top_char)
            bottom_color = PALETTE.get(bottom_char)
            if top_color is None and bottom_color is None:
                line.append(" ")
            elif top_color is None:
                line.append("▄", style=Style(color=bottom_color))
            elif bottom_color is None:
                line.append("▀", style=Style(color=top_color))
            else:
                line.append("▀", style=Style(color=top_color, bgcolor=bottom_color))
        lines.append(line)
    return lines


# 每条 tip 里出现的斜杠命令都必须是已注册命令，参见 tests/test_welcome.py
# 的 test_tips_only_reference_registered_commands。
TIPS: tuple[str, ...] = (
    "Shift+Tab 切权限模式 · /plan 先规划再动手",
    "/worktree 让并发任务各自在独立工作树里改",
    "/skill 看已加载技能 · /help 全部命令",
    "/tasks 查看后台子任务的进度",
    "/memory 管理长期记忆 · /compact 手动压缩上下文",
    "Ctrl+O 折叠或展开工具调用块",
    "/rewind 回退到任意一条历史消息",
    "/trace 查看这一轮的执行轨迹",
    "/session 恢复之前的会话",
    "/sandbox 查看当前的沙箱隔离状态",
)


def pick_tips(count: int, seed: int | None = None) -> list[str]:
    """从 tip 池里抽 count 条。seed 固定时结果可复现，供测试断言。"""
    if count <= 0:
        return []
    return random.Random(seed).sample(TIPS, min(count, len(TIPS)))


def greeting(ctx: WelcomeContext) -> str:
    opener = "Welcome back" if ctx.is_returning else f"Welcome to {ctx.app_name}"
    if ctx.user_name:
        return f"{opener}, {ctx.user_name}!"
    return f"{opener}!"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def readiness_parts(ctx: WelcomeContext) -> list[str]:
    """本次会话装配了什么。计数为 0 的项直接不显示，免得满屏都是 0。"""
    parts: list[str] = []
    if ctx.skills_count:
        parts.append(f"{ctx.skills_count} skills")
    if ctx.agents_count:
        parts.append(f"{ctx.agents_count} agents")
    if ctx.hooks_count:
        parts.append(f"{ctx.hooks_count} hooks")
    if ctx.memory_entries:
        parts.append(f"memory {ctx.memory_entries}")
    if not parts:
        parts.append("no extensions loaded")
    return parts


def mcp_line(state: McpState) -> str | None:
    """MCP 那一行。未配置 MCP 时返回 None，调用方据此整行省略。"""
    if state.kind == "none":
        return None
    if state.kind == "connecting":
        return "MCP · connecting…"
    if state.kind == "ready":
        servers = _plural(state.server_count, "server")
        tools = _plural(state.tool_count, "tool")
        return f"MCP · {servers} · {tools}"
    if state.auth_needed:
        return f"MCP · {state.auth_needed} needs auth · run /mcp"
    return f"MCP · {len(state.errors)} failed · run /mcp"
