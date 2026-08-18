# TUI 启动欢迎卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Koko TUI 常驻顶部的 3 行 banner 换成一张挂进对话流的一次性开屏卡片，展示吉祥物、身份信息、上手提示与本次会话就绪状态。

**Architecture:** 新增 `koko_pi_agent/welcome.py`，一个对 `app.py` 零依赖的纯渲染模块——喂一个 `WelcomeContext` 加一个宽度，返回 Rich renderable，内部自行选择宽/中/窄三档布局。`app.py` 只负责组装 context、把渲染结果塞进一个 `Static` 挂到 `#chat-area`，以及在 MCP 异步初始化完成后原地重渲染。这样三档布局可以脱离 Textual 直接单测。

**Tech Stack:** Python 3.11+、Rich（`Panel` / `Table.grid` / `Group` / `Text`）、Textual（仅 `Static` 挂载）、pytest。

## Global Constraints

- Commit message 用英文（`KOKO.md` 约定）。变量用 snake_case。
- 测试命令一律 `uv run pytest`。本仓库没有配置任何 lint / type-check 工具，不要发明 `ruff` / `mypy` 命令。
- 本计划的测试全部是同步的，不需要 `@pytest.mark.asyncio`。
- `koko_pi_agent/welcome.py` **不得** import `koko_pi_agent/app.py` 的任何东西——这是它可被单测的前提。
- tip 文案里出现的每个斜杠命令都必须是**已注册**命令。可用的只有这 16 个：
  `/help` `/compact` `/clear` `/plan` `/session` `/mcp` `/memory` `/mascot`
  `/permission` `/sandbox` `/rewind` `/status` `/skill` `/worktree` `/tasks` `/trace`。
  **不存在 `/team`**；`commands/handlers/review.py` 里的 `REVIEW_COMMAND` 从未被注册，`/review` 也不可用。
- 像素艺术的背景色一律不显式设置，避免浅色终端下出现黑色色块。
- 设计依据：`docs/superpowers/specs/2026-08-18-tui-welcome-card-design.md`。

---

### Task 1: welcome.py 数据契约与像素渲染引擎

**Files:**
- Create: `koko_pi_agent/welcome.py`
- Test: `tests/test_welcome.py`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces:
  - `PALETTE: dict[str, str]`
  - `MASCOT_LARGE: tuple[str, ...]`（8 个像素行 × 18 列 → 渲染成 4 行文字）
  - `MASCOT_MINI: tuple[str, ...]`（6 个像素行 × 10 列 → 渲染成 3 行文字）
  - `McpKind = Literal["none", "connecting", "ready", "warning"]`
  - `class McpState`：字段 `kind: McpKind = "none"`、`server_count: int = 0`、`tool_count: int = 0`、`auth_needed: int = 0`、`errors: tuple[str, ...] = ()`
  - `class WelcomeContext`：字段见下方代码
  - `render_pixels(rows: tuple[str, ...]) -> list[RichText]`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_welcome.py`：

```python
# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from koko_pi_agent.welcome import (
    MASCOT_LARGE,
    MASCOT_MINI,
    McpState,
    WelcomeContext,
    render_pixels,
)


def test_mascot_art_is_rectangular():
    for art in (MASCOT_LARGE, MASCOT_MINI):
        assert len({len(row) for row in art}) == 1


def test_mascot_art_has_even_pixel_rows():
    # 每两个像素行合成一行半块文字，奇数行会导致最后一行只有上半部分。
    for art in (MASCOT_LARGE, MASCOT_MINI):
        assert len(art) % 2 == 0


def test_mascot_large_renders_four_text_rows():
    assert len(render_pixels(MASCOT_LARGE)) == 4


def test_mascot_mini_renders_three_text_rows():
    assert len(render_pixels(MASCOT_MINI)) == 3


def test_render_pixels_transparent_becomes_blank():
    lines = render_pixels(("..", ".."))
    assert lines[0].plain == "  "


def test_render_pixels_top_only_uses_upper_half_block():
    lines = render_pixels(("o.", ".."))
    assert lines[0].plain == "▀ "


def test_render_pixels_bottom_only_uses_lower_half_block():
    lines = render_pixels(("..", "o."))
    assert lines[0].plain == "▄ "


def test_render_pixels_pads_odd_row_count_with_transparent():
    lines = render_pixels(("oo",))
    assert len(lines) == 1
    assert lines[0].plain == "▀▀"


def test_render_pixels_sets_no_background_for_transparent_lower_half():
    lines = render_pixels(("o.", ".."))
    # 透明的下半格不能带背景色，否则浅色终端上会出现黑块。
    assert lines[0].spans[0].style.bgcolor is None


def test_mcp_state_defaults_to_none_kind():
    assert McpState().kind == "none"


def test_welcome_context_defaults_are_empty():
    ctx = WelcomeContext(
        app_name="Koko",
        app_version="0.3.1",
        model="claude-opus-5",
        provider_name="anthropic",
        work_dir="~/workspace/koko",
    )
    assert ctx.user_name is None
    assert ctx.is_returning is False
    assert ctx.skills_count == 0
    assert ctx.mcp.kind == "none"
    assert ctx.tips_seed is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'koko_pi_agent.welcome'`

- [ ] **Step 3: 写实现**

创建 `koko_pi_agent/welcome.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: PASS，11 passed

- [ ] **Step 5: 提交**

```bash
git add koko_pi_agent/welcome.py tests/test_welcome.py && git commit -m "feat: add welcome card data contract and pixel renderer"
```

---

### Task 2: 文案片段函数

**Files:**
- Modify: `koko_pi_agent/welcome.py`
- Test: `tests/test_welcome.py`

**Interfaces:**
- Consumes: Task 1 的 `WelcomeContext`、`McpState`
- Produces:
  - `TIPS: tuple[str, ...]`
  - `pick_tips(count: int, seed: int | None = None) -> list[str]`
  - `greeting(ctx: WelcomeContext) -> str`
  - `readiness_parts(ctx: WelcomeContext) -> list[str]`
  - `mcp_line(state: McpState) -> str | None`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_welcome.py` 末尾（同时把顶部的 import 换成下面这份）：

```python
from koko_pi_agent.welcome import (
    MASCOT_LARGE,
    MASCOT_MINI,
    TIPS,
    McpState,
    WelcomeContext,
    greeting,
    mcp_line,
    pick_tips,
    readiness_parts,
    render_pixels,
)
```

```python
REGISTERED_COMMANDS = {
    "/help", "/compact", "/clear", "/plan", "/session", "/mcp", "/memory",
    "/mascot", "/permission", "/sandbox", "/rewind", "/status", "/skill",
    "/worktree", "/tasks", "/trace",
}


def _context(**overrides) -> WelcomeContext:
    base = dict(
        app_name="Koko",
        app_version="0.3.1",
        model="claude-opus-5",
        provider_name="anthropic",
        work_dir="~/workspace/koko",
    )
    base.update(overrides)
    return WelcomeContext(**base)


def test_tips_only_reference_registered_commands():
    import re

    for tip in TIPS:
        for command in re.findall(r"/[a-z-]+", tip):
            assert command in REGISTERED_COMMANDS, f"{tip} 引用了未注册命令 {command}"


def test_pick_tips_is_reproducible_with_seed():
    assert pick_tips(3, seed=42) == pick_tips(3, seed=42)


def test_pick_tips_returns_requested_count():
    assert len(pick_tips(3, seed=1)) == 3
    assert len(pick_tips(2, seed=1)) == 2


def test_pick_tips_returns_empty_for_non_positive_count():
    assert pick_tips(0, seed=1) == []
    assert pick_tips(-1, seed=1) == []


def test_pick_tips_caps_at_pool_size():
    assert len(pick_tips(len(TIPS) + 5, seed=1)) == len(TIPS)


def test_greeting_welcomes_back_returning_user():
    assert greeting(_context(is_returning=True, user_name="hh")) == "Welcome back, hh!"


def test_greeting_welcomes_new_user_with_app_name():
    assert greeting(_context(is_returning=False, user_name="hh")) == "Welcome to Koko, hh!"


def test_greeting_omits_name_when_unknown():
    assert greeting(_context(is_returning=True, user_name=None)) == "Welcome back!"
    assert greeting(_context(is_returning=False, user_name=None)) == "Welcome to Koko!"


def test_readiness_parts_lists_non_zero_counts_only():
    parts = readiness_parts(_context(skills_count=12, agents_count=4, hooks_count=0))
    assert parts == ["12 skills", "4 agents"]


def test_readiness_parts_falls_back_when_everything_is_zero():
    assert readiness_parts(_context()) == ["no extensions loaded"]


def test_mcp_line_is_none_when_unconfigured():
    assert mcp_line(McpState(kind="none")) is None


def test_mcp_line_shows_connecting():
    assert mcp_line(McpState(kind="connecting")) == "MCP · connecting…"


def test_mcp_line_shows_ready_counts_with_plurals():
    ready = McpState(kind="ready", server_count=3, tool_count=18)
    assert mcp_line(ready) == "MCP · 3 servers · 18 tools"
    single = McpState(kind="ready", server_count=1, tool_count=1)
    assert mcp_line(single) == "MCP · 1 server · 1 tool"


def test_mcp_line_prefers_auth_over_generic_failure():
    state = McpState(kind="warning", auth_needed=1, errors=("sentry: needs auth",))
    assert mcp_line(state) == "MCP · 1 needs auth · run /mcp"


def test_mcp_line_reports_failures_when_no_auth_needed():
    state = McpState(kind="warning", errors=("a: boom", "b: boom"))
    assert mcp_line(state) == "MCP · 2 failed · run /mcp"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: FAIL，`ImportError: cannot import name 'TIPS' from 'koko_pi_agent.welcome'`

- [ ] **Step 3: 写实现**

在 `koko_pi_agent/welcome.py` 顶部的 import 区加上 `import random`，然后在 `render_pixels` 之后追加：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: PASS，26 passed

- [ ] **Step 5: 提交**

```bash
git add koko_pi_agent/welcome.py tests/test_welcome.py && git commit -m "feat: add welcome card copy builders"
```

---

### Task 3: 三档响应式布局

**Files:**
- Modify: `koko_pi_agent/welcome.py`
- Test: `tests/test_welcome.py`

**Interfaces:**
- Consumes: Task 1 的 `render_pixels` / `MASCOT_LARGE` / `MASCOT_MINI` / `WelcomeContext`；Task 2 的 `greeting` / `pick_tips` / `readiness_parts` / `mcp_line`
- Produces:
  - `WIDE_MIN_WIDTH: int = 100`、`COMPACT_MIN_WIDTH: int = 70`
  - `render_welcome(ctx: WelcomeContext, width: int) -> RenderableType`
  - `render_mcp_warning(ctx: WelcomeContext) -> RichText | None`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_welcome.py`（顶部 import 再补 `render_mcp_warning`、`render_welcome`、`COMPACT_MIN_WIDTH`、`WIDE_MIN_WIDTH`）：

```python
from rich.console import Console


def _lines(ctx: WelcomeContext, width: int) -> list[str]:
    console = Console(width=width, record=True, color_system=None, legacy_windows=False)
    console.print(render_welcome(ctx, width))
    return console.export_text().splitlines()


def test_wide_layout_has_both_columns():
    text = "\n".join(_lines(_context(tips_seed=1, skills_count=12), 120))
    assert "Tips for getting started" in text
    assert "Session ready" in text
    assert "╭" in text


def test_wide_layout_shows_version_in_border_title():
    text = "\n".join(_lines(_context(tips_seed=1), 120))
    assert "Koko v0.3.1" in text


def test_wide_layout_stays_within_height_budget():
    lines = _lines(_context(tips_seed=1, skills_count=12, mcp=McpState(kind="connecting")), 120)
    assert len([line for line in lines if line.strip()]) <= 14


def test_compact_layout_collapses_headings():
    text = "\n".join(_lines(_context(tips_seed=1, skills_count=12), 85))
    assert "Tips" in text
    assert "Ready" in text
    assert "Tips for getting started" not in text
    assert "╭" in text


def test_mini_layout_is_three_borderless_lines():
    lines = [line for line in _lines(_context(skills_count=12), 50) if line.strip()]
    assert len(lines) == 3
    assert "╭" not in "\n".join(lines)


def test_mini_layout_omits_tips():
    text = "\n".join(_lines(_context(tips_seed=1, skills_count=12), 50))
    for tip in TIPS:
        assert tip not in text


def test_layout_boundaries_pick_expected_tier():
    # 100 是宽档下界，99 落到中档；70 是中档下界，69 落到窄档。
    assert "Tips for getting started" in "\n".join(_lines(_context(tips_seed=1), 100))
    assert "Tips for getting started" not in "\n".join(_lines(_context(tips_seed=1), 99))
    assert "╭" in "\n".join(_lines(_context(tips_seed=1), 70))
    assert "╭" not in "\n".join(_lines(_context(tips_seed=1), 69))


def test_all_tiers_survive_empty_context():
    empty = _context(user_name=None, work_dir="")
    for width in (120, 85, 50):
        assert _lines(empty, width)


def test_wide_layout_omits_mcp_line_when_unconfigured():
    text = "\n".join(_lines(_context(tips_seed=1, mcp=McpState(kind="none")), 120))
    assert "MCP" not in text


def test_mcp_warning_is_none_unless_warning_kind():
    for kind in ("none", "connecting", "ready"):
        assert render_mcp_warning(_context(mcp=McpState(kind=kind))) is None


def test_mcp_warning_reports_single_auth_server():
    ctx = _context(mcp=McpState(kind="warning", auth_needed=1, errors=("sentry: auth",)))
    warning = render_mcp_warning(ctx)
    assert warning is not None
    assert warning.plain == " ⚠ 1 MCP server needs authentication · run /mcp"


def test_mcp_warning_pluralises_multiple_auth_servers():
    ctx = _context(mcp=McpState(kind="warning", auth_needed=2, errors=("a", "b")))
    assert render_mcp_warning(ctx).plain == " ⚠ 2 MCP servers need authentication · run /mcp"


def test_mcp_warning_reports_connection_failures():
    ctx = _context(mcp=McpState(kind="warning", errors=("a: boom",)))
    assert render_mcp_warning(ctx).plain == " ⚠ 1 MCP server failed to connect · run /mcp"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: FAIL，`ImportError: cannot import name 'render_welcome' from 'koko_pi_agent.welcome'`

- [ ] **Step 3: 写实现**

把 `koko_pi_agent/welcome.py` 顶部的 import 区改成：

```python
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
```

然后在文件末尾追加：

```python
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
    left: list[RichText] = [RichText(greeting(ctx), style=f"bold {_BRIGHT}"), RichText("")]
    left += [_indent(line, _MASCOT_INDENT) for line in render_pixels(MASCOT_LARGE)]
    left.append(RichText(""))
    left += _identity_lines(ctx)

    right: list[RichText] = [RichText("Tips for getting started", style=f"bold {_ACCENT}")]
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
        RichText(" · ".join(pick_tips(2, ctx.tips_seed)), style=_MUTED,
                 overflow="ellipsis", no_wrap=True),
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
        RichText(" · ".join(summary_parts), style=_MUTED,
                 overflow="ellipsis", no_wrap=True),
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_welcome.py -v`
Expected: PASS，39 passed

若 `test_wide_layout_stays_within_height_budget` 因 `padding=(1, 2)` 导致行数超 14，把 `_panel` 的 padding 改成 `(1, 2)` 之外不要动别的——先确认实际行数，再决定是减一条 tip 还是放宽断言到实际值。不要为了过测试把断言删掉。

- [ ] **Step 5: 提交**

```bash
git add koko_pi_agent/welcome.py tests/test_welcome.py && git commit -m "feat: add three-tier responsive welcome card layout"
```

---

### Task 4: app.py 接入——移除旧 banner，挂载卡片

**Files:**
- Modify: `koko_pi_agent/app.py`（删 `_make_banner` 与 `#title-bar`，加挂载逻辑与 `#cwd-label`）
- Modify: `koko_pi_agent/styles.tcss`（删 `#title-bar` 规则，加三条新规则）

**Interfaces:**
- Consumes: Task 1–3 的 `McpState` / `WelcomeContext` / `render_welcome`
- Produces:
  - `KokoApp._welcome_ctx: WelcomeContext | None`
  - `KokoApp._welcome_card: Static | None`
  - `KokoApp._welcome_width: int`
  - `KokoApp._mount_welcome_card(provider: ProviderConfig, work_dir: str) -> None`
  - 模块级 `_shorten_path(path: str) -> str`、`_detect_user_name(work_dir: str) -> str | None`

- [ ] **Step 1: 加 import 与模块级 helper**

在 `koko_pi_agent/app.py` 的 import 区（`from koko_pi_agent.validator import ...` 一类的同级位置）加：

```python
from koko_pi_agent.welcome import (
    McpState,
    WelcomeContext,
    render_mcp_warning,
    render_welcome,
)
```

在 `_KOKO_THEME` 定义之后、`class KokoApp` 之前加两个模块级函数：

```python
def _shorten_path(path: str) -> str:
    """把 home 前缀换成 ~，让路径在状态栏和卡片里都短一些。"""
    if not path:
        return ""
    try:
        return "~/" + str(Path(path).resolve().relative_to(Path.home()))
    except (ValueError, OSError):
        return path


def _detect_user_name(work_dir: str) -> str | None:
    """问候语里的称呼。配置文件没有这个字段，所以只能从 git 和环境变量猜。

    git config 会 fork 一个 subprocess，设 1 秒超时避免拖慢启动；任何失败都静默降级。
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=work_dir or None,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        name = result.stdout.strip()
        if name:
            return name
    except Exception:
        pass
    return os.environ.get("USER") or None
```

- [ ] **Step 2: 删掉旧 banner**

删除 `_make_banner` 静态方法（`app.py:834-842`，从 `@staticmethod` 那行到 `return t`）：

```python
    @staticmethod
    def _make_banner(model: str = "", work_dir: str = "") -> RichText:
        t = RichText()
        t.append(" /\\_____/\\  ", style="bold color(99)")
        t.append(f"{APP_NAME} v{APP_VERSION}\n", style="color(242)")
        t.append("(  o   o  ) ", style="bold color(99)")
        t.append(f"{model}\n" if model else "\n", style="color(242)")
        t.append(" \\   ^   /  ", style="bold color(99)")
        t.append(work_dir, style="color(242)")
        return t
```

在 `compose()` 里删掉这一行：

```python
        yield Static(self._make_banner(), id="title-bar")
```

- [ ] **Step 3: 状态栏加 cwd 标签**

把 `compose()` 里的 status-bar 块改成（新增 `#cwd-label`，放在 mode 之后）：

```python
            with Horizontal(id="status-bar"):
                yield Static("  default", id="mode-label")
                yield Static("", id="cwd-label")
                yield Static("", id="teammates-label")
                yield Static("", id="model-label")
```

- [ ] **Step 4: 初始化三个新实例属性**

在 `__init__` 里 `self._has_exited_plan_mode: bool = False` 那一行之后加：

```python
        # 开屏欢迎卡片：一次性渲染，宽度只在挂载时结算一次。
        self._welcome_ctx: WelcomeContext | None = None
        self._welcome_card: Static | None = None
        self._welcome_width: int = 0
```

- [ ] **Step 5: 替换 banner 更新点，末尾挂载卡片**

在 `_select_provider_unlocked` 里，把这两行：

```python
        self.query_one("#title-bar", Static).update(
            self._make_banner(provider.model, work_dir)
        )
```

替换成：

```python
        self.query_one("#cwd-label", Static).update(_shorten_path(work_dir))
```

然后在同一个方法的最末尾（`self._notification_check_task = asyncio.create_task(...)` 之后）加：

```python
        self._mount_welcome_card(provider, work_dir)
```

- [ ] **Step 6: 实现挂载方法**

在 `_select_provider_unlocked` 之后加三个方法：

```python
    def _build_welcome_context(
        self, provider: ProviderConfig, work_dir: str
    ) -> WelcomeContext:
        mcp = McpState(kind="connecting") if self._mcp_server_configs else McpState()
        return WelcomeContext(
            app_name=APP_NAME,
            app_version=APP_VERSION,
            model=provider.model,
            provider_name=provider.name,
            work_dir=_shorten_path(work_dir),
            user_name=_detect_user_name(work_dir),
            is_returning=self._has_prior_sessions(),
            skills_count=len(self.skill_loader.get_catalog()) if self.skill_loader else 0,
            agents_count=len(self.agent_loader.list_agents()) if self.agent_loader else 0,
            hooks_count=len(self.hook_engine.hooks) if self.hook_engine else 0,
            memory_entries=(
                len(self.memory_manager.get_memories()) if self.memory_manager else 0
            ),
            mcp=mcp,
        )

    def _has_prior_sessions(self) -> bool:
        """本次会话之前有没有别的会话。

        当前 session 在 `_select_provider_unlocked` 早期就 create() 了，直接判断
        list() 非空会让 is_returning 恒为 True，所以必须按 id 排除自己。
        """
        if self.session_manager is None:
            return False
        current_id = self.session.session_id if self.session else None
        try:
            return any(meta.id != current_id for meta in self.session_manager.list())
        except Exception:
            return False

    def _mount_welcome_card(self, provider: ProviderConfig, work_dir: str) -> None:
        """挂开屏卡片。装饰性组件失败绝不能中断启动流程。"""
        try:
            ctx = self._build_welcome_context(provider, work_dir)
            card = Static(id="welcome-card")
            self._welcome_ctx = ctx
            self._welcome_card = card
            self.query_one("#chat-area", VerticalScroll).mount(card)
            # #chat-area 刚从 display=False 切过来，此刻 size.width 还是 0，
            # 等一帧再按真实宽度渲染。
            self.call_after_refresh(self._render_welcome_card)
        except Exception as exc:
            log.debug("welcome card skipped: %s", exc)
            self._welcome_ctx = None
            self._welcome_card = None

    def _render_welcome_card(self) -> None:
        card = self._welcome_card
        ctx = self._welcome_ctx
        if card is None or ctx is None:
            return
        width = self.query_one("#chat-area").size.width or self.size.width or 80
        self._welcome_width = width
        card.update(render_welcome(ctx, width))
```

- [ ] **Step 7: 更新 styles.tcss**

删掉开头的 `#title-bar` 规则：

```css
#title-bar {
    dock: top;
    width: 100%;
    height: 3;
    padding: 0 1;
}
```

在 `#mode-label` 规则之后加：

```css
#cwd-label {
    width: auto;
    max-width: 40;
    height: 1;
    color: $text-muted;
    padding: 0 1;
    text-overflow: ellipsis;
}
```

在文件末尾加：

```css
#welcome-card {
    width: 100%;
    height: auto;
    padding: 0 1;
}

#welcome-warning {
    width: 100%;
    height: auto;
    padding: 0 1;
}
```

- [ ] **Step 8: 确认没有遗留引用**

Run: `grep -rn "_make_banner\|title-bar" koko_pi_agent/ tests/`
Expected: 无输出。有输出就把残留的引用一并清掉。

- [ ] **Step 9: 跑全量测试**

Run: `uv run pytest`
Expected: PASS，无新增失败。特别留意 `tests/test_input_focus.py` 与 `tests/test_clear.py`——它们会起 TUI，若引用了 `#title-bar` 会在这一步炸出来。

- [ ] **Step 10: 提交**

```bash
git add koko_pi_agent/app.py koko_pi_agent/styles.tcss && git commit -m "feat: replace docked title bar with one-shot welcome card"
```

---

### Task 5: MCP 状态回填与 /clear 安全

**Files:**
- Modify: `koko_pi_agent/app.py`（`_init_mcp` 末尾回填、`_clear_chat` 置空、新增 `_refresh_welcome_mcp`）

**Interfaces:**
- Consumes: Task 4 的 `self._welcome_ctx` / `self._welcome_card` / `self._welcome_width`；Task 3 的 `render_welcome` / `render_mcp_warning`
- Produces: `KokoApp._refresh_welcome_mcp(server_count: int, tool_count: int, errors: list[str]) -> None`

- [ ] **Step 1: 实现回填方法**

在 `_render_welcome_card` 之后加：

```python
    def _refresh_welcome_mcp(
        self, server_count: int, tool_count: int, errors: list[str]
    ) -> None:
        """MCP 异步初始化完成后原地回填卡片。

        卡片可能已经被 /clear 卸载，也可能已经滚出视野——两种情况下更新都是无害的，
        所以不做可见性判断，只在引用为 None 时跳过。
        """
        ctx = self._welcome_ctx
        card = self._welcome_card
        if ctx is None or card is None:
            return
        if errors:
            auth_needed = sum(1 for err in errors if "auth" in err.lower())
            ctx.mcp = McpState(
                kind="warning",
                server_count=server_count,
                tool_count=tool_count,
                auth_needed=auth_needed,
                errors=tuple(errors),
            )
        else:
            ctx.mcp = McpState(
                kind="ready", server_count=server_count, tool_count=tool_count
            )
        # 用挂载时结算的同一宽度重渲染，避免回填导致布局跳档。
        card.update(render_welcome(ctx, self._welcome_width or 80))

        warning = render_mcp_warning(ctx)
        if warning is None:
            return
        existing = self.query("#welcome-warning")
        if existing:
            existing.first(Static).update(warning)
        else:
            self.query_one("#chat-area", VerticalScroll).mount(
                Static(warning, id="welcome-warning"), after=card
            )
```

- [ ] **Step 2: 在 _init_mcp 末尾调用**

在 `_init_mcp` 里，紧跟在这个循环之后：

```python
        for err in connect_result.errors:
            self._show_system_message(f"MCP warning: {err}")
        tools_after = len(self.registry.list_tools())
        mcp_tools = tools_after - tools_before
        server_count = len(connect_result.servers)
```

加一行：

```python
        self._refresh_welcome_mcp(server_count, mcp_tools, list(connect_result.errors))
```

注意必须放在 `server_count` 与 `mcp_tools` 都算出来之后。既有的 `_show_system_message` 循环保持不动——它负责 MCP 失败的即时可见性，卡片下方的警告行只是补充。

- [ ] **Step 3: /clear 时置空引用**

把 `_clear_chat` 改成：

```python
    def _clear_chat(self) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        chat.remove_children()
        # 卡片随对话一起被清掉了，别让 MCP 回填去更新已卸载的 widget。
        self._welcome_card = None
        self._welcome_ctx = None
```

- [ ] **Step 4: 跑全量测试**

Run: `uv run pytest`
Expected: PASS，无新增失败。`tests/test_clear.py` 与 `tests/test_mcp.py` 是重点。

- [ ] **Step 5: 提交**

```bash
git add koko_pi_agent/app.py && git commit -m "feat: backfill MCP status into welcome card"
```

---

### Task 6: 手工验证

**Files:** 无改动（只跑不改；发现问题回到对应 Task 修）

- [ ] **Step 1: 宽档**

把终端拉到 ≥100 列，运行：

```bash
uv run koko
```

确认：圆角边框、标题栏上有 `Koko vX.Y.Z`、左栏是彩色像素柯基加问候语、右栏有 `Tips for getting started` 与 `Session ready`、顶部**没有**残留的 3 行 banner、底部状态栏能看到 cwd。

- [ ] **Step 2: 中档**

终端调到 80 列左右重跑。确认变成单栏堆叠、吉祥物横排在左、`Tips` 与 `Ready` 各一行、没有横向溢出或错位。

- [ ] **Step 3: 窄档**

终端调到 55 列左右重跑。确认是 3 行无边框，且没有任何一行被折行。

- [ ] **Step 4: MCP 回填**

在配了 MCP server 的目录下启动，观察 `MCP · connecting…` 是否在几秒后原地变成 `MCP · N servers · M tools`。再故意配一个跑不起来的 server（比如把 command 改成不存在的可执行文件），确认卡片下方出现黄色 `⚠ ... run /mcp`，同时既有的 `MCP warning:` 系统消息仍然照常出现。

- [ ] **Step 5: 无 MCP**

在没有任何 MCP 配置的目录启动，确认卡片里完全没有 `MCP` 字样，也没有警告行。

- [ ] **Step 6: /clear**

启动后执行 `/clear`，确认卡片被清掉且不报错。若此时 MCP 仍在连接中，等它连完，确认没有异常抛出。

- [ ] **Step 7: 首次 vs 回访**

在一个从没用过 Koko 的目录启动，确认问候语是 `Welcome to Koko`；在当前仓库启动，确认是 `Welcome back`。

---

## Self-Review

**Spec 覆盖检查：**

| Spec 章节 | 对应任务 |
|---|---|
| 数据契约（`WelcomeContext` / `McpState`） | Task 1 |
| 像素艺术实现（半块、无背景色） | Task 1 |
| Tips 池与抽样（含"只用已注册命令"约束） | Task 2 |
| 问候语首次/回访、就绪概览、MCP 行文案 | Task 2 |
| 三档渲染规格与宽度阈值 | Task 3 |
| `render_mcp_warning` | Task 3 |
| 挂载生命周期（含 `call_after_refresh` 宽度结算） | Task 4 |
| 删除 `#title-bar`、cwd 补偿到状态栏 | Task 4 |
| `user_name` 三级降级与 1 秒超时 | Task 4 |
| `is_returning` 排除当前 session | Task 4（`_has_prior_sessions`） |
| MCP 回填与警告行 | Task 5 |
| `/clear` 置空引用 | Task 5 |
| 错误处理（挂载失败不中断启动） | Task 4 Step 6 的 try/except |
| 测试策略六项 | Task 1–3 的测试 |

Spec 的「非目标」清单（git 分支、resize 重排、`-p`/`--remote` 欢迎屏、吉祥物动画、What's new）在本计划里没有任何任务触碰，符合预期。

**类型一致性检查：** `McpState` 的字段名（`kind` / `server_count` / `tool_count` / `auth_needed` / `errors`）在 Task 1 定义，Task 2 的 `mcp_line`、Task 3 的 `render_mcp_warning`、Task 5 的 `_refresh_welcome_mcp` 用的是同一组名字。`render_welcome(ctx, width)` 的两参签名在 Task 3 定义，Task 4 `_render_welcome_card` 与 Task 5 `_refresh_welcome_mcp` 调用一致。`_welcome_ctx` / `_welcome_card` / `_welcome_width` 三个属性在 Task 4 Step 4 声明，Task 5 复用。

**已知偏差：** Spec 的模块划分里写了 `MASCOT_WIDE` / `MASCOT_COMPACT` / `MASCOT_MINI` 三个常量，但因为宽档与中档共用同一张图（spec 正文也这么说），本计划只定义 `MASCOT_LARGE` 与 `MASCOT_MINI` 两个常量。这是 DRY 化，不改变任何渲染结果。
