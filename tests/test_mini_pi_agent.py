from __future__ import annotations

import asyncio
from typing import cast

import pytest
from pydantic import BaseModel

from examples.mini_pi_agent.agent import Agent
from examples.mini_pi_agent.fake_llm import ScriptedLLMClient
from examples.mini_pi_agent.models import (
    LoopFailedEvent,
    LoopFinishedEvent,
    ModelResponse,
    PermissionDecision,
    ToolCall,
    ToolFinishedEvent,
    ToolResult,
)
from examples.mini_pi_agent.registry import ToolRegistry
from examples.mini_pi_agent.tools import CalculatorTool


async def collect(agent: Agent, prompt: str):
    return [event async for event in agent.prompt(prompt)]


def calculator_call(**arguments: object) -> ModelResponse:
    return ModelResponse(
        tool_calls=(ToolCall("call-1", "calculator", dict(arguments)),),
        stop_reason="tool_use",
    )


def test_agent_runs_tool_and_finishes() -> None:
    model = ScriptedLLMClient(
        [
            calculator_call(operator="add", left=20, right=22),
            ModelResponse(text="答案是 42"),
        ]
    )
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    agent = Agent(model, registry)
    events = asyncio.run(collect(agent, "计算 20 + 22"))

    finished = cast(LoopFinishedEvent, events[-1])
    assert isinstance(finished, LoopFinishedEvent)
    assert finished.final_text == "答案是 42"
    assert finished.total_turns == 2
    assert [message.role for message in agent.state.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert agent.state.messages[2].content == "42.0"
    assert len(model.requests) == 2


def test_unknown_tool_becomes_recoverable_result() -> None:
    model = ScriptedLLMClient(
        [
            ModelResponse(
                tool_calls=(ToolCall("call-1", "missing", {}),),
                stop_reason="tool_use",
            ),
            ModelResponse(text="我改用别的方法回答"),
        ]
    )
    agent = Agent(model, ToolRegistry())

    events = asyncio.run(collect(agent, "调用一个不存在的工具"))

    tool_event = next(event for event in events if isinstance(event, ToolFinishedEvent))
    assert tool_event.result.is_error is True
    assert tool_event.result.output == "unknown tool: missing"
    assert isinstance(events[-1], LoopFinishedEvent)


def test_invalid_arguments_are_rejected_before_execution() -> None:
    model = ScriptedLLMClient(
        [calculator_call(operator="add", left=20), ModelResponse(text="参数有误")]
    )
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    events = asyncio.run(collect(Agent(model, registry), "参数不完整"))

    tool_event = next(event for event in events if isinstance(event, ToolFinishedEvent))
    assert tool_event.result.is_error is True
    assert "parameter validation failed" in tool_event.result.output


class CountingParams(BaseModel):
    value: int


class CountingTool:
    name = "counter"
    description = "Record whether execution happened."
    params_model = CountingParams

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, params: BaseModel) -> ToolResult:
        self.calls += 1
        return ToolResult(str(cast(CountingParams, params).value))


def test_permission_denial_prevents_execution() -> None:
    model = ScriptedLLMClient(
        [
            ModelResponse(
                tool_calls=(ToolCall("call-1", "counter", {"value": 1}),),
                stop_reason="tool_use",
            ),
            ModelResponse(text="操作被拒绝"),
        ]
    )
    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)

    async def deny(_call, _tool):
        return PermissionDecision.deny("需要用户批准")

    events = asyncio.run(
        collect(Agent(model, registry, before_tool_call=deny), "执行")
    )

    tool_event = next(event for event in events if isinstance(event, ToolFinishedEvent))
    assert tool.calls == 0
    assert tool_event.result == ToolResult("需要用户批准", is_error=True)


def test_loop_stops_at_max_turns() -> None:
    model = ScriptedLLMClient(
        [
            calculator_call(operator="add", left=1, right=1),
            calculator_call(operator="add", left=1, right=1),
        ]
    )
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    events = asyncio.run(collect(Agent(model, registry, max_turns=2), "一直计算"))

    assert isinstance(events[-1], LoopFailedEvent)
    assert events[-1].total_turns == 2


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    with pytest.raises(ValueError, match="tool already registered"):
        registry.register(CalculatorTool())
