from __future__ import annotations

import re
from unittest.mock import AsyncMock, call

import pytest

from koko_pi_agent.commands.registry import Command, CommandRegistry, CommandType
from koko_pi_agent.remote import RemoteServer
from koko_pi_agent.web_content import INDEX_HTML


def _make_server_with_mascot_command() -> tuple[RemoteServer, AsyncMock]:
    server = RemoteServer(providers=[])
    registry = CommandRegistry()
    handler = AsyncMock()
    registry.register_sync(
        Command(
            name="mascot",
            aliases=["mew", "cat"],
            description="Show the ASCII mascot",
            type=CommandType.LOCAL_UI,
            handler=handler,
        )
    )
    server.command_registry = registry
    server._broadcast = AsyncMock()  # type: ignore[method-assign]
    return server, handler


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/mascot", "/mew", "/cat"])
async def test_remote_mascot_command_and_aliases_broadcast_in_order(
    command: str,
) -> None:
    server, handler = _make_server_with_mascot_command()

    await server._handle_slash_command(command)

    assert server._broadcast.await_args_list == [  # type: ignore[attr-defined]
        call({"type": "mascot_show", "data": None}),
        call({"type": "command_done", "data": None}),
    ]
    handler.assert_not_awaited()


def test_remote_page_contains_self_contained_ascii_mascot() -> None:
    start = INDEX_HTML.index('<div id="mascot-overlay"')
    end = INDEX_HTML.index("</div>", start) + len("</div>")
    mascot_markup = INDEX_HTML[start:end]

    assert 'id="mascot-close"' in mascot_markup
    assert 'type="button"' in mascot_markup
    assert 'id="mascot-art"' in mascot_markup
    assert 'aria-label="MewCode animated ASCII corgi"' in mascot_markup
    assert "<img" not in mascot_markup
    assert "http://" not in mascot_markup
    assert "https://" not in mascot_markup
    assert "position: fixed" in INDEX_HTML
    assert "top: 64px" in INDEX_HTML
    assert "right: 20px" in INDEX_HTML


def test_remote_mascot_has_three_equal_size_corgi_frames() -> None:
    frames_block = re.search(
        r"const mascotFrames = \[(.*?)\]\.map\(frame => frame\.trimEnd\(\)\);",
        INDEX_HTML,
        re.DOTALL,
    )
    assert frames_block is not None
    frames = [
        frame.rstrip()
        for frame in re.findall(r"String\.raw`(.*?)`", frames_block.group(1), re.DOTALL)
    ]

    assert len(frames) == 3
    dimensions = {
        (len(frame.splitlines()), max(len(line) for line in frame.splitlines()))
        for frame in frames
    }
    assert dimensions == {(9, 19)}
    assert all("/\\       /\\" in frame for frame in frames)
    assert any("U" in frame for frame in frames)


def test_remote_mascot_animation_starts_and_stops_with_overlay() -> None:
    assert "const MASCOT_FRAME_MS = 360;" in INDEX_HTML
    assert "mascotArt.textContent = mascotFrames[mascotFrameIndex];" in INDEX_HTML
    assert "mascotTimer = window.setInterval" in INDEX_HTML
    assert "window.clearInterval(mascotTimer);" in INDEX_HTML
    assert "startMascotAnimation();" in INDEX_HTML
    assert "stopMascotAnimation();" in INDEX_HTML


def test_remote_page_wires_show_click_and_escape_behaviors() -> None:
    assert "case 'mascot_show':\n      showMascot();" in INDEX_HTML
    assert "mascotOverlay.classList.add('show');" in INDEX_HTML
    assert "mascotClose.addEventListener('click', hideMascot);" in INDEX_HTML
    assert "event.key === 'Escape'" in INDEX_HTML
    assert "mascotOverlay.classList.contains('show')" in INDEX_HTML
    assert "hideMascot();" in INDEX_HTML


def test_remote_mascot_uses_pointer_dragging_and_viewport_clamping() -> None:
    for event_name in (
        "pointerdown",
        "pointermove",
        "pointerup",
        "pointercancel",
        "lostpointercapture",
    ):
        assert f"mascotOverlay.addEventListener('{event_name}'" in INDEX_HTML

    assert "mascotOverlay.setPointerCapture(event.pointerId);" in INDEX_HTML
    assert "mascotOverlay.releasePointerCapture(pointerId);" in INDEX_HTML
    assert "mascotClose.contains(event.target)" in INDEX_HTML
    assert "mascotClose.addEventListener('pointerdown'" in INDEX_HTML
    assert "event.stopPropagation()" in INDEX_HTML
    assert "window.innerWidth - rect.width" in INDEX_HTML
    assert "window.innerHeight - rect.height" in INDEX_HTML
    assert "Math.min(Math.max(left, MASCOT_VIEWPORT_GAP), maxLeft)" in INDEX_HTML
    assert "Math.min(Math.max(top, MASCOT_VIEWPORT_GAP), maxTop)" in INDEX_HTML
    assert "window.addEventListener('resize'" in INDEX_HTML
    assert "window.requestAnimationFrame(keepMascotInViewport);" in INDEX_HTML
    assert "touch-action: none" in INDEX_HTML
