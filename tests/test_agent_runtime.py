from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from mewcode.agent import Agent
from mewcode.client import LLMClient
from mewcode.conversation import ConversationManager
from mewcode.permissions import Decision, PermissionMode
from mewcode.runtime import (
    HeadlessApprovalAdapter,
    InteractiveApprovalAdapter,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStatus,
)
from mewcode.tools import ToolRegistry
from mewcode.tools.base import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    Tool,
    ToolCallComplete,
    ToolResult,
)


class _ScriptedClient(LLMClient):
    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self._responses = responses
        self._index = 0

    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        response = self._responses[self._index]
        self._index += 1
        for event in response:
            yield event


class _EmptyParams(BaseModel):
    pass


class _EchoTool(Tool):
    name = "Echo"
    description = "echo"
    params_model = _EmptyParams
    is_concurrency_safe = True

    async def execute(self, params: _EmptyParams) -> ToolResult:
        return ToolResult(output="echoed")


class _CountingTool(_EchoTool):
    name = "Count"

    def __init__(self, counter: list[str]) -> None:
        self._counter = counter

    async def execute(self, params: _EmptyParams) -> ToolResult:
        self._counter.append("executed")
        return ToolResult(output="executed")


def _script() -> list[list[StreamEvent]]:
    return [
        [
            ToolCallComplete("call", "Echo", {}),
            StreamEnd("tool_use", input_tokens=1, output_tokens=1),
        ],
        [
            TextDelta("done"),
            StreamEnd("end_turn", input_tokens=2, output_tokens=1),
        ],
    ]


def _conversation_projection(conversation: ConversationManager):
    return [
        (
            message.role,
            message.content,
            [
                (tool.tool_use_id, tool.tool_name, tool.arguments)
                for tool in message.tool_uses
            ],
            [
                (result.tool_use_id, result.content, result.is_error)
                for result in message.tool_results
            ],
        )
        for message in conversation.history[1:]
    ]


@pytest.mark.asyncio
async def test_streaming_remote_sink_and_headless_share_one_loop_semantics() -> None:
    conversations = []

    streaming_registry = ToolRegistry()
    streaming_registry.register(_EchoTool())
    streaming_agent = Agent(_ScriptedClient(_script()), streaming_registry, "anthropic")
    streaming_conversation = ConversationManager()
    streaming_conversation.add_user_message("go")
    async for _event in streaming_agent.run(streaming_conversation):
        pass
    conversations.append(streaming_conversation)

    remote_registry = ToolRegistry()
    remote_registry.register(_EchoTool())
    remote_agent = Agent(_ScriptedClient(_script()), remote_registry, "anthropic")
    remote_conversation = ConversationManager()
    remote_conversation.add_user_message("go")

    async def remote_sink(_event) -> None:
        return None

    remote_run = remote_agent.start_run(
        remote_conversation,
        remote_sink,
        approval=InteractiveApprovalAdapter(),
    )
    await remote_run.wait_until_idle()
    conversations.append(remote_conversation)

    headless_registry = ToolRegistry()
    headless_registry.register(_EchoTool())
    headless_agent = Agent(_ScriptedClient(_script()), headless_registry, "anthropic")
    headless_conversation = ConversationManager()
    headless_conversation.add_user_message("go")
    assert await headless_agent.run_to_completion("", headless_conversation) == "done"
    conversations.append(headless_conversation)

    projections = [_conversation_projection(item) for item in conversations]
    assert projections[0] == projections[1] == projections[2]


@pytest.mark.asyncio
async def test_hook_rejection_is_identical_in_streaming_and_headless() -> None:
    class _RejectingHooks:
        async def run_hooks(self, event, context) -> None:
            return None

        async def run_pre_tool_hooks(self, context):
            return SimpleNamespace(reason="blocked by test hook")

        def drain_notifications(self):
            return []

        def get_prompt_messages(self):
            return []

    conversations = []
    for headless in (False, True):
        counter: list[str] = []
        registry = ToolRegistry()
        registry.register(_CountingTool(counter))
        agent = Agent(
            _ScriptedClient(
                [
                    [
                        ToolCallComplete("call", "Count", {}),
                        StreamEnd("tool_use", 1, 1),
                    ],
                    [TextDelta("done"), StreamEnd("end_turn", 1, 1)],
                ]
            ),
            registry,
            "anthropic",
            hook_engine=_RejectingHooks(),
        )
        conversation = ConversationManager()
        conversation.add_user_message("go")
        if headless:
            await agent.run_to_completion("", conversation)
        else:
            async for _event in agent.run(conversation):
                pass
        assert counter == []
        conversations.append(conversation)

    assert _conversation_projection(conversations[0]) == _conversation_projection(
        conversations[1]
    )
    result = next(
        result
        for message in conversations[0].history
        for result in message.tool_results
    )
    assert result.is_error is True
    assert "Hook rejected" in result.content


@pytest.mark.asyncio
async def test_permission_denial_is_identical_in_streaming_and_headless() -> None:
    class _DenyChecker:
        mode = PermissionMode.DEFAULT
        plan_file_path = ""

        def check(self, tool, arguments):
            return Decision(effect="deny", reason="blocked by test policy")

    conversations = []
    for headless in (False, True):
        counter: list[str] = []
        registry = ToolRegistry()
        registry.register(_CountingTool(counter))
        agent = Agent(
            _ScriptedClient(
                [
                    [
                        ToolCallComplete("call", "Count", {}),
                        StreamEnd("tool_use", 1, 1),
                    ],
                    [TextDelta("done"), StreamEnd("end_turn", 1, 1)],
                ]
            ),
            registry,
            "anthropic",
            permission_checker=_DenyChecker(),
        )
        conversation = ConversationManager()
        conversation.add_user_message("go")
        if headless:
            await agent.run_to_completion("", conversation)
        else:
            async for _event in agent.run(conversation):
                pass
        assert counter == []
        conversations.append(conversation)

    assert _conversation_projection(conversations[0]) == _conversation_projection(
        conversations[1]
    )
    result = next(
        result
        for message in conversations[0].history
        for result in message.tool_results
    )
    assert result.is_error is True
    assert "Permission denied" in result.content


@pytest.mark.asyncio
async def test_headless_ask_is_safely_denied() -> None:
    class _AskChecker:
        mode = PermissionMode.DEFAULT
        plan_file_path = ""

        def check(self, tool, arguments):
            return Decision(effect="ask", reason="confirmation required")

    counter: list[str] = []
    registry = ToolRegistry()
    registry.register(_CountingTool(counter))
    agent = Agent(
        _ScriptedClient(
            [
                [
                    ToolCallComplete("call", "Count", {}),
                    StreamEnd("tool_use", 1, 1),
                ],
                [TextDelta("done"), StreamEnd("end_turn", 1, 1)],
            ]
        ),
        registry,
        "anthropic",
        permission_checker=_AskChecker(),
    )
    conversation = ConversationManager()

    assert await agent.run_to_completion("go", conversation) == "done"
    assert counter == []
    result = next(
        result for message in conversation.history for result in message.tool_results
    )
    assert result.is_error is True
    assert "rejected" in result.content.lower()


@pytest.mark.asyncio
async def test_model_error_becomes_failed_run_result() -> None:
    class _FailingClient(LLMClient):
        async def stream(self, conversation, system="", tools=None):
            raise RuntimeError("model unavailable")
            yield StreamEnd("end_turn")

    agent = Agent(_FailingClient(), ToolRegistry(), "anthropic")
    events = []

    async def sink(event) -> None:
        events.append(event)

    run = agent.start_run(ConversationManager(), sink)
    result = await run.wait_until_idle()

    assert result.status == "failed"
    assert result.error == "model unavailable"
    assert any(isinstance(event, RunFailed) for event in events)

    headless = Agent(_FailingClient(), ToolRegistry(), "anthropic")
    with pytest.raises(RuntimeError, match="model unavailable"):
        await headless.run_to_completion("go")


@pytest.mark.asyncio
async def test_max_turns_is_a_run_result_not_a_second_loop() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    agent = Agent(
        _ScriptedClient(
            [
                [
                    ToolCallComplete("call", "Echo", {}),
                    StreamEnd("tool_use", 1, 1),
                ]
            ]
        ),
        registry,
        "anthropic",
        max_iterations=1,
    )

    async def sink(_event) -> None:
        return None

    run = agent.start_run(ConversationManager(), sink)
    result = await run.wait_until_idle()

    assert result.status == "max_turns"
    assert result.turns == 1


@pytest.mark.asyncio
async def test_max_tokens_tool_call_is_paired_without_execution() -> None:
    counter: list[str] = []
    registry = ToolRegistry()
    registry.register(_CountingTool(counter))
    agent = Agent(
        _ScriptedClient(
            [
                [
                    ToolCallComplete("truncated", "Count", {}),
                    StreamEnd("max_tokens", 1, 1),
                ],
                [TextDelta("recovered"), StreamEnd("end_turn", 1, 1)],
            ]
        ),
        registry,
        "anthropic",
    )
    conversation = ConversationManager()

    result = await agent.run_to_completion("go", conversation)

    assert result == "recovered"
    assert counter == []
    tool_results = [
        result for message in conversation.history for result in message.tool_results
    ]
    assert len(tool_results) == 1
    assert tool_results[0].tool_use_id == "truncated"
    assert tool_results[0].is_error is True
    assert "truncated" in tool_results[0].content.lower()


@pytest.mark.asyncio
async def test_agent_rejects_a_second_concurrent_run() -> None:
    entered = asyncio.Event()

    class _BlockingClient(LLMClient):
        async def stream(self, conversation, system="", tools=None):
            entered.set()
            await asyncio.Event().wait()
            yield StreamEnd("end_turn")

    agent = Agent(_BlockingClient(), ToolRegistry(), "anthropic")

    async def sink(_event) -> None:
        return None

    first = agent.start_run(ConversationManager(), sink)
    await entered.wait()
    with pytest.raises(RuntimeError, match="active run"):
        agent.start_run(ConversationManager(), sink)
    first.cancel()
    result = await first.wait_until_idle()
    assert result.status == "cancelled"
    assert agent.active_run is None


@pytest.mark.asyncio
async def test_run_cancelled_before_first_schedule_still_settles() -> None:
    agent = Agent(_ScriptedClient(_script()), ToolRegistry(), "anthropic")

    async def sink(_event) -> None:
        return None

    run = agent.start_run(ConversationManager(), sink)
    run.cancel()
    result = await asyncio.wait_for(run.wait_until_idle(), timeout=1)

    assert result.status == "cancelled"
    assert run.status == RunStatus.IDLE
    assert agent.active_run is None


@pytest.mark.asyncio
async def test_explicitly_closing_streaming_events_settles_the_run() -> None:
    class _NeverCompletes(LLMClient):
        async def stream(self, conversation, system="", tools=None):
            await asyncio.Event().wait()
            yield StreamEnd("end_turn")

    agent = Agent(_NeverCompletes(), ToolRegistry(), "anthropic")
    events = agent.run(ConversationManager())
    first = await anext(events)
    assert isinstance(first, RunStarted)

    await events.aclose()

    assert agent.active_run is None


@pytest.mark.asyncio
async def test_run_finished_is_observed_before_run_becomes_idle() -> None:
    client = _ScriptedClient([[TextDelta("done"), StreamEnd("end_turn", 1, 1)]])
    agent = Agent(client, ToolRegistry(), "anthropic")
    statuses = []
    run = None

    async def sink(event) -> None:
        if isinstance(event, RunFinished):
            assert run is not None
            statuses.append(run.status)

    run = agent.start_run(
        ConversationManager(),
        sink,
        approval=HeadlessApprovalAdapter(agent.permission_mode),
    )
    result = await run.wait_until_idle()

    assert result.status == "completed"
    assert statuses == [RunStatus.RUNNING]
    assert run.status == RunStatus.IDLE
    assert agent.active_run is None


@pytest.mark.asyncio
async def test_cancelled_tool_is_paired_and_no_run_task_remains() -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    class _SlowTool(_EchoTool):
        name = "Slow"
        is_concurrency_safe = False

        async def execute(self, params: _EmptyParams) -> ToolResult:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            return ToolResult(output="unreachable")

    registry = ToolRegistry()
    registry.register(_SlowTool())
    client = _ScriptedClient(
        [[ToolCallComplete("slow", "Slow", {}), StreamEnd("tool_use", 1, 1)]]
    )
    agent = Agent(client, registry, "anthropic")
    conversation = ConversationManager()

    async def sink(_event) -> None:
        return None

    run = agent.start_run(conversation, sink)
    await started.wait()
    run.cancel()
    run.cancel()
    result = await run.wait_until_idle()

    assert result.status == "cancelled"
    assert stopped.is_set()
    assert run.status == RunStatus.IDLE
    assert agent.active_run is None
    tool_results = [
        result for message in conversation.history for result in message.tool_results
    ]
    assert len(tool_results) == 1
    assert tool_results[0].tool_use_id == "slow"
    assert tool_results[0].is_error is True
    assert "cancelled" in tool_results[0].content.lower()
