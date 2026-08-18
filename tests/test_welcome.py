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
