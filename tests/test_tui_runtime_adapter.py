from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from mewcode.app import ChatInput, MewCodeApp
from mewcode.client import LLMClient
from mewcode.config import ProviderConfig
from mewcode.extensions import ToolProfile, tool_names_for_profile
from mewcode.runtime import RunControl, RunInputKind
from mewcode.tools.base import StreamEnd, TextDelta


class _GatedClient(LLMClient):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def stream(self, conversation, system="", tools=None):
        self.calls += 1
        if self.calls == 1:
            yield TextDelta("first answer")
            self.entered.set()
            await self.release.wait()
            yield StreamEnd("end_turn", input_tokens=1, output_tokens=1)
            return
        yield TextDelta("second answer")
        yield StreamEnd("end_turn", input_tokens=1, output_tokens=1)


def test_chat_input_maps_alt_enter_to_follow_up() -> None:
    bindings = {(binding.key, binding.action) for binding in ChatInput.BINDINGS}
    assert ("enter", "submit") in bindings
    assert ("alt+enter", "submit_follow_up") in bindings
    assert ChatInput.Submitted("later", RunInputKind.FOLLOW_UP).delivery is (
        RunInputKind.FOLLOW_UP
    )


def test_tui_provider_initialization_is_awaitable() -> None:
    assert inspect.iscoroutinefunction(MewCodeApp._select_provider)


@pytest.mark.asyncio
async def test_tui_provider_owns_tui_profile_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    async def skip_context_resolution(_provider) -> None:
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.app.create_client", lambda _provider: object())
    monkeypatch.setattr(
        "mewcode.app.resolve_context_window",
        skip_context_resolution,
    )
    app = MewCodeApp(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ],
        enable_fork=False,
        ui_state_path=tmp_path / "ui-state.json",
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.runtime is not None
        assert app.agent is app.runtime.agent
        assert app.registry is app.runtime.registry
        assert tuple(tool.name for tool in app.registry.list_tools()) == (
            tool_names_for_profile(ToolProfile.TUI_LEAD)
        )
        assert {
            contribution.owner.extension_id
            for contribution in app.registry.list_contributions()
        } == {"mewcode.builtin-tools"}

        first_runtime = app.runtime
        await app._select_provider(
            ProviderConfig(
                name="second",
                protocol="anthropic",
                base_url="http://unused",
                model="second-model",
            )
        )
        assert first_runtime.state == "closed"
        assert app.runtime is not first_runtime
        assert app.runtime is not None
        assert app.runtime.state == "active"

        runtime = app.runtime
        await app._shutdown_runtime()
        assert runtime.state == "closed"
        assert runtime.registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_concurrent_provider_initialization_leaves_one_active_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    async def skip_context_resolution(_provider) -> None:
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.app.create_client", lambda _provider: object())
    monkeypatch.setattr(
        "mewcode.app.resolve_context_window",
        skip_context_resolution,
    )
    providers = [
        ProviderConfig(
            name=name,
            protocol="anthropic",
            base_url="http://unused",
            model=f"model-{name}",
        )
        for name in ("first", "second")
    ]
    app = MewCodeApp(
        providers=providers,
        enable_fork=False,
        ui_state_path=tmp_path / "ui-state.json",
    )
    opened = []

    from mewcode.runtime import AgentRuntime

    open_runtime = AgentRuntime.open.__func__

    async def recording_open(cls, request, *, extension_host):
        runtime = await open_runtime(
            cls,
            request,
            extension_host=extension_host,
        )
        opened.append(runtime)
        return runtime

    monkeypatch.setattr(AgentRuntime, "open", classmethod(recording_open))

    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.gather(
            app._select_provider(providers[0]),
            app._select_provider(providers[1]),
        )

        assert len(opened) == 2
        assert opened[0].state == "closed"
        assert opened[0].registry.list_contributions() == ()
        assert app.runtime is opened[1]
        assert opened[1].state == "active"

        await app._shutdown_runtime()


@pytest.mark.asyncio
async def test_tui_active_inputs_queue_without_mutating_conversation(
    tmp_path,
    monkeypatch,
) -> None:
    async def skip_context_resolution(_provider) -> None:
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.app.create_client", lambda _provider: object())
    monkeypatch.setattr(
        "mewcode.app.resolve_context_window",
        skip_context_resolution,
    )
    app = MewCodeApp(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ],
        enable_fork=False,
        ui_state_path=tmp_path / "ui-state.json",
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.runtime is not None
        control = RunControl()
        monkeypatch.setattr(
            app.runtime,
            "steer_active_run",
            lambda text: control.enqueue(RunInputKind.STEERING, text),
        )
        monkeypatch.setattr(
            app.runtime,
            "follow_up_active_run",
            lambda text: control.enqueue(RunInputKind.FOLLOW_UP, text),
        )
        before = list(app.conversation.history)
        app._streaming = True

        await app._dispatch_command("change direction", RunInputKind.STEERING)
        await app._dispatch_command("after you finish", RunInputKind.FOLLOW_UP)
        await pilot.pause()

        assert app.conversation.history == before
        assert control.pending_count == 2
        assert len(app.query(".user-row")) == 2
        app._streaming = False


@pytest.mark.asyncio
async def test_tui_real_run_delivers_and_persists_steering_once(
    tmp_path,
    monkeypatch,
) -> None:
    client = _GatedClient()

    async def skip_context_resolution(_provider) -> None:
        return None

    async def no_side_query(_query: str) -> str:
        return ""

    async def no_summary() -> None:
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.app.create_client", lambda _provider: client)
    monkeypatch.setattr(
        "mewcode.app.resolve_context_window",
        skip_context_resolution,
    )
    app = MewCodeApp(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ],
        enable_fork=False,
        ui_state_path=tmp_path / "ui-state.json",
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "_prefetch_relevant_memories", no_side_query)
        monkeypatch.setattr(app, "_update_session_summary", no_summary)

        await app._dispatch_command("first prompt")
        run_task = app._agent_task
        assert run_task is not None
        await asyncio.wait_for(client.entered.wait(), timeout=2)
        await app._dispatch_command("change direction", RunInputKind.STEERING)
        client.release.set()
        await asyncio.wait_for(run_task, timeout=3)
        await pilot.pause()

        contents = [message.content for message in app.conversation.history]
        assert contents.count("first prompt") == 1
        assert contents.count("change direction") == 1
        assert contents.count("first answer") == 1
        assert contents.count("second answer") == 1

        assert app.session is not None
        session_path = app.session._sessions_dir / f"{app.session.session_id}.jsonl"
        records = [json.loads(line) for line in session_path.read_text().splitlines()]
        persisted = [record.get("content") for record in records]
        assert persisted.count("first prompt") == 1
        assert persisted.count("change direction") == 1
        assert persisted.count("first answer") == 1
        assert persisted.count("second answer") == 1
