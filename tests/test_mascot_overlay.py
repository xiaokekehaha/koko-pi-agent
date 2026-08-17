from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, OptionList, Static

import koko_pi_agent.app as app_module
from koko_pi_agent.app import ChatInput, MewCodeApp
from koko_pi_agent.config import ProviderConfig
from koko_pi_agent.mascot_overlay import ASCII_MASCOT, CORGI_FRAMES, MascotOverlay
from koko_pi_agent.ui_state import UIStateStore


class MascotTestApp(App[None]):
    CSS = "Screen { layers: default mascot; }"

    def compose(self) -> ComposeResult:
        yield Static("background", id="background")
        yield MascotOverlay(id="mascot-overlay")


class MewCodeMascotTestApp(MewCodeApp):
    CSS_PATH = str(Path(app_module.__file__).with_name("styles.tcss"))

    def __init__(self, ui_state_path: Path) -> None:
        provider = ProviderConfig("test", "openai", "http://unused", "test")
        super().__init__(providers=[provider], ui_state_path=ui_state_path)

    async def _select_provider(self, provider: ProviderConfig) -> None:
        self._selected_provider = provider
        self.query_one("#chat-area").display = True
        self.query_one("#input-area").display = True
        self.query_one(ChatInput).focus()


class FakeTimer:
    def __init__(self, callback, paused: bool) -> None:
        self.callback = callback
        self.paused = paused
        self.resume_calls = 0
        self.pause_calls = 0

    def resume(self) -> None:
        self.paused = False
        self.resume_calls += 1

    def pause(self) -> None:
        self.paused = True
        self.pause_calls += 1


def test_corgi_animation_frames_have_stable_geometry() -> None:
    dimensions = [tuple(len(line) for line in frame.splitlines()) for frame in CORGI_FRAMES]
    assert len(CORGI_FRAMES) >= 3
    assert all(dimension == dimensions[0] for dimension in dimensions)
    assert "/\\     /\\" in CORGI_FRAMES[0]


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
async def test_corgi_animation_cycles_and_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, FakeTimer] = {}

    def fake_set_interval(
        self,
        interval,
        callback,
        *,
        name=None,
        repeat=0,
        pause=False,
    ) -> FakeTimer:
        timer = FakeTimer(callback, pause)
        captured["timer"] = timer
        return timer

    monkeypatch.setattr(MascotOverlay, "set_interval", fake_set_interval)
    app = MascotTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)
        art = app.query_one("#mascot-art", Static)
        timer = captured["timer"]
        assert timer.paused is True

        overlay.show_mascot()
        assert timer.resume_calls == 1
        rendered = [art.render().plain]
        for _ in CORGI_FRAMES:
            timer.callback()
            await pilot.pause()
            rendered.append(art.render().plain)
        assert rendered == [*CORGI_FRAMES, CORGI_FRAMES[0]]

        overlay.close_mascot()
        assert timer.paused is True
        assert timer.pause_calls == 1


@pytest.mark.asyncio
async def test_mascot_can_be_dragged_and_stays_inside_screen() -> None:
    app = MascotTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)
        overlay.show_mascot()
        await pilot.pause()

        art = app.query_one("#mascot-art", Static)
        start = overlay.region
        pointer_x = art.region.x + 10
        pointer_y = art.region.y + 3

        await pilot.mouse_down("#mascot-art", offset=(10, 3))
        assert app.mouse_captured is overlay
        assert app.screen._selecting is False
        await pilot.hover(None, offset=(pointer_x - 15, pointer_y + 4))
        await pilot.mouse_up(None, offset=(pointer_x - 15, pointer_y + 4))
        await pilot.pause()

        assert overlay.region.x == start.x - 15
        assert overlay.region.y == start.y + 4
        assert app.mouse_captured is None

        await pilot.mouse_down(overlay, offset=(10, 3))
        await pilot.hover(None, offset=(0, 0))
        await pilot.mouse_up(None, offset=(0, 0))
        await pilot.pause()

        assert overlay.region.x >= app.screen.region.x
        assert overlay.region.y >= app.screen.region.y
        assert overlay.region.right <= app.screen.region.right
        assert overlay.region.bottom <= app.screen.region.bottom


@pytest.mark.asyncio
async def test_slash_command_opens_mascot_and_close_restores_input_focus(
    tmp_path: Path,
) -> None:
    app = MewCodeMascotTestApp(tmp_path / "ui_state.json")
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


@pytest.mark.asyncio
async def test_open_mascot_restores_on_restart_until_explicitly_closed(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "ui_state.json"

    first_app = MewCodeMascotTestApp(state_path)
    async with first_app.run_test(size=(80, 24)) as pilot:
        chat_input = first_app.query_one(ChatInput)
        chat_input.insert("/mascot")
        await pilot.press("enter")
        await pilot.pause()
        assert first_app.query_one(MascotOverlay).is_open is True
        assert UIStateStore(state_path).mascot_open is True

    second_app = MewCodeMascotTestApp(state_path)
    async with second_app.run_test(size=(80, 24)) as pilot:
        overlay = second_app.query_one(MascotOverlay)
        chat_input = second_app.query_one(ChatInput)
        assert overlay.is_open is True
        assert chat_input.has_focus is True
        assert second_app.query_one("#mascot-close", Button).has_focus is False

        await pilot.click("#mascot-close")
        await pilot.pause()
        assert overlay.is_open is False
        assert UIStateStore(state_path).mascot_open is False

    third_app = MewCodeMascotTestApp(state_path)
    async with third_app.run_test(size=(80, 24)):
        assert third_app.query_one(MascotOverlay).is_open is False


@pytest.mark.asyncio
async def test_auto_restore_keeps_provider_picker_focus(tmp_path: Path) -> None:
    state_path = tmp_path / "ui_state.json"
    UIStateStore(state_path).set_mascot_open(True)
    providers = [
        ProviderConfig("one", "openai", "http://unused", "test"),
        ProviderConfig("two", "openai", "http://unused", "test"),
    ]
    app = MewCodeApp(providers=providers, ui_state_path=state_path)

    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)
        picker = app.query_one("#provider-list", OptionList)
        assert overlay.is_open is True
        assert picker.has_focus is True
        assert app.query_one("#mascot-close", Button).has_focus is False

        await pilot.click("#mascot-close")
        await pilot.pause()
        assert overlay.is_open is False
        assert picker.has_focus is True


@pytest.mark.asyncio
async def test_escape_closes_restored_mascot_and_persists_closed_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "ui_state.json"
    UIStateStore(state_path).set_mascot_open(True)
    app = MewCodeMascotTestApp(state_path)

    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MascotOverlay)
        assert overlay.is_open is True
        assert app.query_one(ChatInput).has_focus is True

        await pilot.press("escape")
        await pilot.pause()
        assert overlay.is_open is False
        assert UIStateStore(state_path).mascot_open is False
