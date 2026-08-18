# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""启动欢迎卡片的纯渲染层。

对 `app.py` 零依赖：喂一个 `WelcomeContext` 和一个终端宽度，返回 Rich renderable。
布局选档、配色、tip 抽样都封在这里，外部无需知道。
"""

from __future__ import annotations

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
