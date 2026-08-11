from __future__ import annotations

from pathlib import Path

import pytest

import mewcode.app as app_module
from mewcode.app import ChatInput, ChatTranscript, MewCodeApp, ToolCallBlock
from mewcode.config import ProviderConfig


class InputFocusTestApp(MewCodeApp):
    CSS_PATH = str(Path(app_module.__file__).with_name("styles.tcss"))

    def __init__(self, ui_state_path: Path) -> None:
        provider = ProviderConfig("test", "openai", "http://unused", "test")
        super().__init__(providers=[provider], ui_state_path=ui_state_path)

    def _select_provider(self, provider: ProviderConfig) -> None:
        self._selected_provider = provider
        self.query_one("#chat-area").display = True
        self.query_one("#input-area").display = True
        self.query_one(ChatInput).focus(scroll_visible=False)


@pytest.mark.asyncio
async def test_clicking_chat_keeps_composer_ready_for_typing(tmp_path: Path) -> None:
    app = InputFocusTestApp(tmp_path / "ui_state.json")

    async with app.run_test(size=(80, 24)) as pilot:
        chat_input = app.query_one(ChatInput)

        await pilot.click("#chat-area")
        await pilot.pause()
        await pilot.press("h", "i")

        assert chat_input.has_focus is True
        assert chat_input.text == "hi"


@pytest.mark.asyncio
async def test_tool_click_toggles_and_returns_focus_to_composer(
    tmp_path: Path,
) -> None:
    app = InputFocusTestApp(tmp_path / "ui_state.json")

    async with app.run_test(size=(80, 24)) as pilot:
        transcript = app.query_one(ChatTranscript)
        block = ToolCallBlock("ReadFile", {"file_path": "demo.py"})
        block.set_result("print('hello')", is_error=False, elapsed=0.1)
        await transcript.mount(block)
        await pilot.pause()

        assert block._collapsed is True
        await pilot.click(block)
        await pilot.pause()
        await pilot.press("x")

        chat_input = app.query_one(ChatInput)
        assert block._collapsed is False
        assert chat_input.has_focus is True
        assert chat_input.text == "x"


@pytest.mark.asyncio
async def test_composer_has_a_visible_focus_state(tmp_path: Path) -> None:
    app = InputFocusTestApp(tmp_path / "ui_state.json")

    async with app.run_test(size=(80, 24)) as pilot:
        chat_input = app.query_one(ChatInput)
        transcript = app.query_one(ChatTranscript)

        assert chat_input.has_focus is True
        focused_style = (chat_input.styles.border, chat_input.styles.background)

        transcript.focus(scroll_visible=False)
        await pilot.pause()
        blurred_style = (chat_input.styles.border, chat_input.styles.background)

        assert chat_input.has_focus is False
        assert focused_style != blurred_style


@pytest.mark.asyncio
async def test_clicking_chat_does_not_steal_an_intentional_disabled_state(
    tmp_path: Path,
) -> None:
    app = InputFocusTestApp(tmp_path / "ui_state.json")

    async with app.run_test(size=(80, 24)) as pilot:
        chat_input = app.query_one(ChatInput)
        transcript = app.query_one(ChatTranscript)
        chat_input.disabled = True
        transcript.focus(scroll_visible=False)
        await pilot.pause()

        await pilot.click(transcript)
        await pilot.pause()

        assert chat_input.has_focus is False
