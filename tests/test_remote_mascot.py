from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from mewcode.commands.registry import Command, CommandRegistry, CommandType
from mewcode.remote import RemoteServer
from mewcode.web_content import INDEX_HTML


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
    assert "/\\_/\\" in mascot_markup
    assert "<img" not in mascot_markup
    assert "http://" not in mascot_markup
    assert "https://" not in mascot_markup
    assert "position: fixed" in INDEX_HTML
    assert "top: 64px" in INDEX_HTML
    assert "right: 20px" in INDEX_HTML


def test_remote_page_wires_show_click_and_escape_behaviors() -> None:
    assert "case 'mascot_show':\n      showMascot();" in INDEX_HTML
    assert "mascotOverlay.classList.add('show');" in INDEX_HTML
    assert "mascotClose.addEventListener('click', hideMascot);" in INDEX_HTML
    assert "event.key === 'Escape'" in INDEX_HTML
    assert "mascotOverlay.classList.contains('show')" in INDEX_HTML
    assert "hideMascot();" in INDEX_HTML
