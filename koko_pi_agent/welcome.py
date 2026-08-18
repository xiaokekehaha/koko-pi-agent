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

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
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


# 布局选档阈值：宽档双栏，中档单栏堆叠，窄档三行无边框。
WIDE_MIN_WIDTH = 100
COMPACT_MIN_WIDTH = 70

_ACCENT = "#D9843B"
_BRIGHT = "#F5F0E8"
_MUTED = "#8A8A8A"
_BORDER = "#3A3A3A"
_TITLE = "#875FFF"
_WARN = "#E5A50A"

_LEFT_COLUMN_WIDTH = 32
_MASCOT_INDENT = 3


def _indent(text: RichText, amount: int) -> RichText:
    out = RichText(" " * amount)
    out.append_text(text)
    return out


def _panel(body: RenderableType, ctx: WelcomeContext) -> Panel:
    title = RichText(f" {ctx.app_name} v{ctx.app_version} ", style=f"bold {_TITLE}")
    return Panel(
        body,
        title=title,
        title_align="left",
        box=box.ROUNDED,
        border_style=_BORDER,
        padding=(1, 2),
    )


def _identity_lines(ctx: WelcomeContext) -> list[RichText]:
    lines = [RichText(f"{ctx.model} · {ctx.provider_name}", style=_MUTED)]
    if ctx.work_dir:
        lines.append(RichText(ctx.work_dir, style=_MUTED))
    return lines


def _render_wide(ctx: WelcomeContext) -> Panel:
    left: list[RichText] = [
        RichText(greeting(ctx), style=f"bold {_BRIGHT}"),
        RichText(""),
    ]
    left += [_indent(line, _MASCOT_INDENT) for line in render_pixels(MASCOT_LARGE)]
    left.append(RichText(""))
    left += _identity_lines(ctx)

    right: list[RichText] = [
        RichText("Tips for getting started", style=f"bold {_ACCENT}")
    ]
    right += [RichText(f"  {tip}", style=_MUTED) for tip in pick_tips(3, ctx.tips_seed)]
    right.append(RichText(""))
    right.append(RichText("Session ready", style=f"bold {_ACCENT}"))
    right.append(RichText("  " + " · ".join(readiness_parts(ctx)), style=_MUTED))
    status = mcp_line(ctx.mcp)
    if status:
        right.append(RichText(f"  {status}", style=_MUTED))

    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=_LEFT_COLUMN_WIDTH)
    grid.add_column(ratio=1)
    grid.add_row(Group(*left), Group(*right))
    return _panel(grid, ctx)


def _render_compact(ctx: WelcomeContext) -> Panel:
    pixels = render_pixels(MASCOT_LARGE)
    info: list[RichText] = [RichText(greeting(ctx), style=f"bold {_BRIGHT}")]
    info += _identity_lines(ctx)
    while len(info) < len(pixels):
        info.append(RichText(""))

    head = Table.grid(padding=(0, 2))
    head.add_column(width=len(MASCOT_LARGE[0]))
    head.add_column(ratio=1)
    for pixel_line, info_line in zip(pixels, info):
        head.add_row(pixel_line, info_line)

    summary = " · ".join(readiness_parts(ctx))
    status = mcp_line(ctx.mcp)
    if status:
        summary = f"{summary} · {status}"

    body = Table.grid(padding=(0, 1))
    body.add_column(width=6)
    body.add_column(ratio=1)
    body.add_row(
        RichText("Tips", style=f"bold {_ACCENT}"),
        RichText(
            " · ".join(pick_tips(2, ctx.tips_seed)),
            style=_MUTED,
            overflow="ellipsis",
            no_wrap=True,
        ),
    )
    body.add_row(
        RichText("Ready", style=f"bold {_ACCENT}"),
        RichText(summary, style=_MUTED, overflow="ellipsis", no_wrap=True),
    )
    return _panel(Group(head, RichText(""), body), ctx)


def _render_mini(ctx: WelcomeContext) -> RenderableType:
    summary_parts = readiness_parts(ctx)[:2]
    status = mcp_line(ctx.mcp)
    if status:
        summary_parts.append(status)

    right = [
        RichText(f"{ctx.app_name} v{ctx.app_version} · {ctx.model}", style=_BRIGHT),
        RichText(ctx.work_dir or ctx.provider_name, style=_MUTED),
        RichText(
            " · ".join(summary_parts), style=_MUTED, overflow="ellipsis", no_wrap=True
        ),
    ]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=len(MASCOT_MINI[0]))
    grid.add_column(ratio=1)
    for pixel_line, text_line in zip(render_pixels(MASCOT_MINI), right):
        grid.add_row(pixel_line, text_line)
    return grid


def render_welcome(ctx: WelcomeContext, width: int) -> RenderableType:
    """按终端宽度选档渲染欢迎卡片。宽度只在挂载时取一次，不随 resize 变化。"""
    if width >= WIDE_MIN_WIDTH:
        return _render_wide(ctx)
    if width >= COMPACT_MIN_WIDTH:
        return _render_compact(ctx)
    return _render_mini(ctx)


def render_mcp_warning(ctx: WelcomeContext) -> RichText | None:
    """卡片下方那行黄色警告。只在 MCP 真的出问题时返回非 None。"""
    state = ctx.mcp
    if state.kind != "warning":
        return None
    line = RichText(" ⚠ ", style=f"bold {_WARN}")
    if state.auth_needed:
        count = state.auth_needed
        noun = "server" if count == 1 else "servers"
        verb = "needs" if count == 1 else "need"
        line.append(f"{count} MCP {noun} {verb} authentication · run /mcp", style=_WARN)
    else:
        count = len(state.errors)
        noun = "server" if count == 1 else "servers"
        line.append(f"{count} MCP {noun} failed to connect · run /mcp", style=_WARN)
    return line
