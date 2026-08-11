from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from mewcode.mascot_overlay import ASCII_MASCOT, MascotOverlay


class MascotTestApp(App[None]):
    CSS = "Screen { layers: default mascot; }"

    def compose(self) -> ComposeResult:
        yield Static("background", id="background")
        yield MascotOverlay(id="mascot-overlay")


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
