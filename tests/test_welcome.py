# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

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
