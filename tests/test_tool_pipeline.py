from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

from mewcode.permissions import Decision
from mewcode.runtime import (
    CompletedAssistantMessage,
    RunCancellation,
    ToolBatchRequest,
    ToolExecutionStarted,
    ToolPipeline,
    ToolResultEvent,
)
from mewcode.tools import ToolRegistry
from mewcode.tools.base import Tool, ToolCallComplete, ToolResult


class _Params(BaseModel):
    delay: float = 0


class _ControlledTool(Tool):
    description = "controlled test tool"
    params_model = _Params
    category = "read"

    def __init__(
        self,
        name: str,
        state: _ExecutionState,
        *,
        concurrency_safe: bool,
        terminate: bool = False,
    ) -> None:
        self.name = name
        self.is_concurrency_safe = concurrency_safe
        self._state = state
        self._terminate = terminate

    async def execute(self, params: _Params) -> ToolResult:
        self._state.active += 1
        self._state.max_active = max(self._state.max_active, self._state.active)
        if not self.is_concurrency_safe and self._state.active != 1:
            self._state.unsafe_overlapped = True
        self._state.started.append(self.name)
        self._state.timeline.append(("start", self.name))
        try:
            await asyncio.sleep(params.delay)
            return ToolResult(output=self.name, terminate=self._terminate)
        finally:
            self._state.active -= 1
            self._state.finished.append(self.name)
            self._state.timeline.append(("finish", self.name))


@dataclass
class _ExecutionState:
    active: int = 0
    max_active: int = 0
    unsafe_overlapped: bool = False
    started: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    timeline: list[tuple[str, str]] = field(default_factory=list)


async def _run_pipeline(
    pipeline: ToolPipeline,
    calls: list[ToolCallComplete],
    tmp_path: Path,
    *,
    stop_reason: str = "tool_use",
):
    events = []

    async def emit(event) -> None:
        events.append(event)

    result = await pipeline.execute_batch(
        ToolBatchRequest(
            assistant_message=CompletedAssistantMessage(
                text="",
                tool_calls=tuple(calls),
                stop_reason=stop_reason,
            ),
            session_dir=tmp_path,
        ),
        emit,
        RunCancellation(),
    )
    return result, events


@pytest.mark.asyncio
async def test_truncated_batch_never_executes_tools(tmp_path: Path) -> None:
    state = _ExecutionState()
    registry = ToolRegistry()
    registry.register(_ControlledTool("SideEffect", state, concurrency_safe=False))
    calls = [
        ToolCallComplete("one", "SideEffect", {}),
        ToolCallComplete("two", "SideEffect", {}),
    ]

    result, events = await _run_pipeline(
        ToolPipeline(registry), calls, tmp_path, stop_reason="max_tokens"
    )

    assert state.started == []
    assert len(result.messages) == 2
    assert all(message.is_error for message in result.messages)
    assert [message.tool_use_id for message in result.messages] == ["one", "two"]
    assert not any(isinstance(event, ToolExecutionStarted) for event in events)


@pytest.mark.asyncio
async def test_prepare_failures_still_pair_one_result_per_call(
    tmp_path: Path,
) -> None:
    state = _ExecutionState()
    registry = ToolRegistry()
    registry.register(_ControlledTool("Disabled", state, concurrency_safe=True))
    registry.register(_ControlledTool("Validated", state, concurrency_safe=True))
    registry.disable("Disabled")
    calls = [
        ToolCallComplete("unknown", "Missing", {}),
        ToolCallComplete("disabled", "Disabled", {}),
        ToolCallComplete("invalid", "Validated", {"delay": "not-a-number"}),
    ]

    result, events = await _run_pipeline(ToolPipeline(registry), calls, tmp_path)

    assert [message.tool_use_id for message in result.messages] == [
        "unknown",
        "disabled",
        "invalid",
    ]
    assert all(message.is_error for message in result.messages)
    assert state.started == []
    completions = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(completions) == len(calls)


@pytest.mark.asyncio
async def test_hook_and_approval_exceptions_are_paired_results(
    tmp_path: Path,
) -> None:
    class _BrokenPreHook:
        async def run_pre_tool_hooks(self, context):
            raise RuntimeError("pre hook crashed")

        def drain_notifications(self):
            return []

    class _AskChecker:
        def check(self, tool, arguments):
            return Decision(effect="ask", reason="confirm")

    class _BrokenApproval:
        async def approve(self, tool_name, description, emit):
            raise RuntimeError("approval crashed")

    class _BrokenPostHook:
        async def run_pre_tool_hooks(self, context):
            return None

        async def run_hooks(self, event, context):
            raise RuntimeError("post hook crashed")

        def drain_notifications(self):
            return []

    call = [ToolCallComplete("call", "Controlled", {})]

    pre_state = _ExecutionState()
    pre_registry = ToolRegistry()
    pre_registry.register(
        _ControlledTool("Controlled", pre_state, concurrency_safe=False)
    )
    pre_result, _ = await _run_pipeline(
        ToolPipeline(pre_registry, hook_engine=_BrokenPreHook()), call, tmp_path
    )
    assert pre_state.started == []
    assert pre_result.messages[0].is_error is True
    assert "Pre-tool hook error" in pre_result.messages[0].content

    approval_state = _ExecutionState()
    approval_registry = ToolRegistry()
    approval_registry.register(
        _ControlledTool("Controlled", approval_state, concurrency_safe=False)
    )
    approval_result, _ = await _run_pipeline(
        ToolPipeline(
            approval_registry,
            permission_checker=_AskChecker(),
            approval=_BrokenApproval(),
        ),
        call,
        tmp_path,
    )
    assert approval_state.started == []
    assert approval_result.messages[0].is_error is True
    assert "Permission approval error" in approval_result.messages[0].content

    post_state = _ExecutionState()
    post_registry = ToolRegistry()
    post_registry.register(
        _ControlledTool("Controlled", post_state, concurrency_safe=False)
    )
    post_result, _ = await _run_pipeline(
        ToolPipeline(post_registry, hook_engine=_BrokenPostHook()), call, tmp_path
    )
    assert post_state.started == ["Controlled"]
    assert post_result.messages[0].is_error is True
    assert "Post-tool hook error" in post_result.messages[0].content


@pytest.mark.asyncio
async def test_safe_groups_run_concurrently_but_unsafe_tool_is_a_barrier(
    tmp_path: Path,
) -> None:
    state = _ExecutionState()
    registry = ToolRegistry()
    registry.register(_ControlledTool("slow", state, concurrency_safe=True))
    registry.register(_ControlledTool("fast", state, concurrency_safe=True))
    registry.register(_ControlledTool("barrier", state, concurrency_safe=False))
    registry.register(_ControlledTool("last", state, concurrency_safe=True))
    calls = [
        ToolCallComplete("1", "slow", {"delay": 0.03}),
        ToolCallComplete("2", "fast", {"delay": 0.001}),
        ToolCallComplete("3", "barrier", {"delay": 0.001}),
        ToolCallComplete("4", "last", {"delay": 0.001}),
    ]

    result, events = await _run_pipeline(ToolPipeline(registry), calls, tmp_path)

    assert state.max_active == 2
    assert state.unsafe_overlapped is False
    assert state.timeline.index(("start", "barrier")) > state.timeline.index(
        ("finish", "slow")
    )
    assert state.timeline.index(("start", "last")) > state.timeline.index(
        ("finish", "barrier")
    )
    assert [message.tool_use_id for message in result.messages] == ["1", "2", "3", "4"]
    completion_order = [
        event.tool_name for event in events if isinstance(event, ToolResultEvent)
    ]
    assert completion_order[:2] == ["fast", "slow"]


@pytest.mark.asyncio
async def test_terminate_is_result_semantics_not_tool_name(tmp_path: Path) -> None:
    state = _ExecutionState()
    registry = ToolRegistry()
    registry.register(
        _ControlledTool(
            "AnyTerminalTool", state, concurrency_safe=False, terminate=True
        )
    )

    result, _events = await _run_pipeline(
        ToolPipeline(registry),
        [ToolCallComplete("terminal", "AnyTerminalTool", {})],
        tmp_path,
    )

    assert result.terminate is True
