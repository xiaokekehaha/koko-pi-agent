from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import ValidationError

from examples.mini_pi_agent.contracts import BeforeToolCall, LLMClient, Tool
from examples.mini_pi_agent.models import (
    AgentEvent,
    AgentState,
    LoopFailedEvent,
    LoopFinishedEvent,
    Message,
    PermissionDecision,
    TextEvent,
    ToolCall,
    ToolFinishedEvent,
    ToolResult,
    ToolStartedEvent,
)
from examples.mini_pi_agent.registry import ToolRegistry


async def _allow_all(_call: ToolCall, _tool: Tool) -> PermissionDecision:
    return PermissionDecision.allow()


async def _execute_tool(
    call: ToolCall,
    registry: ToolRegistry,
    before_tool_call: BeforeToolCall,
) -> ToolResult:
    tool = registry.get(call.name)
    if tool is None:
        return ToolResult(f"unknown tool: {call.name}", is_error=True)

    try:
        params = tool.params_model.model_validate(call.arguments)
    except ValidationError as exc:
        return ToolResult(f"parameter validation failed: {exc}", is_error=True)

    try:
        decision = await before_tool_call(call, tool)
    except Exception as exc:
        return ToolResult(f"permission check failed: {exc}", is_error=True)
    if not decision.allowed:
        reason = decision.reason or "permission denied"
        return ToolResult(reason, is_error=True)

    try:
        return await tool.execute(params)
    except Exception as exc:
        return ToolResult(f"tool execution failed: {exc}", is_error=True)


async def run_agent_loop(
    state: AgentState,
    model: LLMClient,
    registry: ToolRegistry,
    *,
    before_tool_call: BeforeToolCall | None = None,
    max_turns: int = 8,
) -> AsyncIterator[AgentEvent]:
    """Run a minimal model -> tool -> model loop.

    The loop owns no session object. All mutable state is passed in explicitly.
    """

    permission_check = before_tool_call or _allow_all

    for turn in range(1, max_turns + 1):
        try:
            response = await model.complete(tuple(state.messages), registry.schemas())
        except Exception as exc:
            yield LoopFailedEvent(f"model call failed: {exc}", total_turns=turn)
            return

        state.messages.append(
            Message(
                role="assistant",
                content=response.text,
                tool_calls=response.tool_calls,
            )
        )
        if response.text:
            yield TextEvent(response.text)

        if not response.tool_calls:
            yield LoopFinishedEvent(response.text, total_turns=turn)
            return

        for call in response.tool_calls:
            yield ToolStartedEvent(call)
            result = await _execute_tool(call, registry, permission_check)
            state.messages.append(
                Message(
                    role="tool",
                    content=result.output,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    is_error=result.is_error,
                )
            )
            yield ToolFinishedEvent(call, result)

    yield LoopFailedEvent(
        f"agent reached the maximum of {max_turns} turns",
        total_turns=max_turns,
    )
