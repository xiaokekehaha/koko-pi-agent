from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

import mewcode.app as app_module
from mewcode.app import ChatInput, MewCodeApp
from mewcode.mascot_overlay import ASCII_MASCOT, MascotOverlay


class MascotTestApp(App[None]):
    CSS = "Screen { layers: default mascot; }"

    def compose(self) -> ComposeResult:
        yield Static("background", id="background")
        yield MascotOverlay(id="mascot-overlay")


class MewCodeMascotTestApp(MewCodeApp):
    CSS_PATH = str(Path(app_module.__file__).with_name("styles.tcss"))

    def __init__(self) -> None:
        super().__init__(providers=[])

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#chat-area").display = True
        self.query_one("#input-area").display = True
        self.query_one(ChatInput).focus()


@pytest.mark.asyncio
async def test_mascot_is_floating_and_clicking_x_closes_it() -> None:
    app = MascotTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)
        assert overlay.is_open is False

        overlay.show_mascot()
        await pilot.pause()

        assert overlay.is_open is True
        assert app.query_one("#mascot-art", Static).render().plain == ASCII_MASCOT
        assert overlay.region.right <= app.screen.region.right
        assert overlay.region.x > app.screen.region.x
        assert app.query_one("#mascot-close", Button).has_focus is True

        await pilot.click("#mascot-close")
        await pilot.pause()
        assert overlay.is_open is False


@pytest.mark.asyncio
async def test_mascot_reopens_without_duplicate_and_escape_closes_it() -> None:
    app = MascotTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)

        overlay.show_mascot()
        overlay.show_mascot()
        await pilot.pause()
        assert len(app.query(MascotOverlay)) == 1

        await pilot.press("escape")
        await pilot.pause()
        assert overlay.is_open is False

        overlay.show_mascot()
        await pilot.pause()
        assert overlay.is_open is True


@pytest.mark.asyncio
async def test_slash_command_opens_mascot_and_close_restores_input_focus() -> None:
    app = MewCodeMascotTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        chat_input = app.query_one(ChatInput)
        chat_input.insert("/mascot")
        await pilot.press("enter")
        await pilot.pause()

        overlay = app.query_one(MascotOverlay)
        assert overlay.is_open is True
        assert len(app.query(MascotOverlay)) == 1

        await pilot.click("#mascot-close")
        await pilot.pause()
        assert overlay.is_open is False
        assert chat_input.has_focus is True
