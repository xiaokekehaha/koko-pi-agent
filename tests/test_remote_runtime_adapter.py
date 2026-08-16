from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from mewcode.agent import Agent
from mewcode.client import LLMClient
from mewcode.config import ProviderConfig
from mewcode.conversation import ConversationManager
from mewcode.extensions import ToolProfile, tool_names_for_profile
from mewcode.remote import RemoteServer
from mewcode.runtime import (
    QueuedRunInput,
    RunFinished,
    RunInputClosedError,
    RunInputDelivered,
    RunInputKind,
    RunResult,
)
from mewcode.tools import ToolRegistry
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


@pytest.mark.asyncio
async def test_remote_initialization_owns_remote_profile_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.remote.create_client", lambda _provider: object())
    server = RemoteServer(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ]
    )

    await server._init_agent()

    assert server.runtime is not None
    assert server.agent is server.runtime.agent
    assert server.registry is server.runtime.registry
    assert tuple(tool.name for tool in server.registry.list_tools()) == (
        tool_names_for_profile(ToolProfile.REMOTE_LEAD)
    )
    assert {
        contribution.owner.extension_id
        for contribution in server.registry.list_contributions()
    } == {"mewcode.builtin-tools"}

    runtime = server.runtime
    await server._shutdown()
    assert runtime.state == "closed"
    assert runtime.registry.list_contributions() == ()


@dataclass
class _AsyncCloser:
    name: str
    order: list[str]

    async def shutdown(self) -> None:
        self.order.append(self.name)

    async def aclose(self) -> None:
        self.order.append(self.name)


@dataclass
class _SyncCloser:
    name: str
    order: list[str]

    def close(self) -> None:
        self.order.append(self.name)


@pytest.mark.asyncio
async def test_remote_shutdown_is_ordered_and_idempotent() -> None:
    order: list[str] = []
    server = RemoteServer(providers=[])
    server.mcp_manager = _AsyncCloser("mcp", order)
    server.runtime = _AsyncCloser("runtime", order)
    server.session = _SyncCloser("session", order)

    await server._shutdown()
    await server._shutdown()

    assert order == ["mcp", "runtime", "session"]


class _QueueingRuntime:
    def __init__(self) -> None:
        from mewcode.runtime import RunControl

        self.control = RunControl()

    def steer_active_run(self, text: str):
        return self.control.enqueue(RunInputKind.STEERING, text)

    def follow_up_active_run(self, text: str):
        return self.control.enqueue(RunInputKind.FOLLOW_UP, text)


@pytest.mark.asyncio
async def test_remote_active_inputs_return_typed_queued_ack() -> None:
    server = RemoteServer(providers=[])
    runtime = _QueueingRuntime()
    server.runtime = runtime
    server._streaming = True
    messages = []

    async def broadcast(message) -> None:
        messages.append(message)

    server._broadcast = broadcast

    await server._handle_user_message("change", RunInputKind.STEERING)
    await server._handle_user_message("later", RunInputKind.FOLLOW_UP)

    assert runtime.control.pending_count == 2
    assert [message["type"] for message in messages] == [
        "input_queued",
        "input_queued",
    ]
    assert [message["data"]["delivery"] for message in messages] == [
        "steering",
        "follow_up",
    ]


@pytest.mark.asyncio
async def test_remote_broadcasts_delivered_and_restored_run_inputs() -> None:
    delivered = QueuedRunInput("delivered", RunInputKind.STEERING, "change")
    restored = QueuedRunInput("restored", RunInputKind.FOLLOW_UP, "later")

    class _EventAgent:
        async def run(self, conversation):
            yield RunInputDelivered(
                kind=RunInputKind.STEERING,
                input_ids=(delivered.input_id,),
            )
            yield RunFinished(
                run_id="run",
                result=RunResult(
                    status="cancelled",
                    turns=0,
                    final_text="",
                    undelivered_inputs=(restored,),
                ),
            )

    server = RemoteServer(providers=[])
    server.agent = _EventAgent()
    server.conversation = ConversationManager()
    messages = []

    async def broadcast(message) -> None:
        messages.append(message)

    server._broadcast = broadcast
    await server._handle_user_message("initial")

    assert [message["type"] for message in messages] == [
        "input_delivered",
        "input_restored",
        "run_finished",
    ]
    assert messages[1]["data"]["inputs"] == [
        {
            "id": "restored",
            "delivery": "follow_up",
            "content": "later",
        }
    ]


@pytest.mark.asyncio
async def test_remote_sealed_race_retries_as_a_new_run() -> None:
    class _SealedRuntime:
        def steer_active_run(self, text: str):
            raise RunInputClosedError("sealed")

    class _CompletingAgent:
        async def run(self, conversation):
            yield RunFinished(
                run_id="new-run",
                result=RunResult(status="completed", turns=1, final_text="ok"),
            )

    server = RemoteServer(providers=[])
    server.runtime = _SealedRuntime()
    server.agent = _CompletingAgent()
    server.conversation = ConversationManager()
    server._streaming = True
    server._run_idle.clear()
    messages = []

    async def broadcast(message) -> None:
        messages.append(message)

    server._broadcast = broadcast
    pending = asyncio.create_task(server._handle_user_message("not lost"))
    await asyncio.sleep(0)
    assert not pending.done()

    server._streaming = False
    server._run_idle.set()
    await pending

    assert any(
        message.role == "user" and message.content == "not lost"
        for message in server.conversation.history
    )
    assert [message["type"] for message in messages] == ["run_finished"]


@pytest.mark.asyncio
async def test_remote_real_run_delivers_steering_through_runtime_facade() -> None:
    client = _GatedClient()
    agent = Agent(client, ToolRegistry(), "anthropic")

    class _LiveRuntime:
        def steer_active_run(self, text: str):
            active_run = agent.active_run
            return active_run.steer(text) if active_run is not None else None

        def follow_up_active_run(self, text: str):
            active_run = agent.active_run
            return active_run.follow_up(text) if active_run is not None else None

    server = RemoteServer(providers=[])
    server.runtime = _LiveRuntime()
    server.agent = agent
    server.conversation = ConversationManager()
    messages = []

    async def broadcast(message) -> None:
        messages.append(message)

    server._broadcast = broadcast
    first = asyncio.create_task(server._handle_user_message("first prompt"))
    await asyncio.wait_for(client.entered.wait(), timeout=2)
    await server._handle_user_message("change direction", RunInputKind.STEERING)
    client.release.set()
    await asyncio.wait_for(first, timeout=3)

    contents = [message.content for message in server.conversation.history]
    assert contents.count("first prompt") == 1
    assert contents.count("change direction") == 1
    assert contents.count("first answer") == 1
    assert contents.count("second answer") == 1
    assert [message["type"] for message in messages].count("input_queued") == 1
    assert [message["type"] for message in messages].count("input_delivered") == 1
    assert messages[-1] == {
        "type": "run_finished",
        "data": {"status": "completed"},
    }
