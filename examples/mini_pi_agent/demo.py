from __future__ import annotations

import asyncio

from examples.mini_pi_agent.agent import Agent
from examples.mini_pi_agent.fake_llm import ScriptedLLMClient
from examples.mini_pi_agent.models import (
    LoopFailedEvent,
    LoopFinishedEvent,
    ModelResponse,
    TextEvent,
    ToolCall,
    ToolFinishedEvent,
    ToolStartedEvent,
)
from examples.mini_pi_agent.registry import ToolRegistry
from examples.mini_pi_agent.tools import CalculatorTool, TextLengthTool


async def main() -> None:
    model = ScriptedLLMClient(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="calculator",
                        arguments={"operator": "add", "left": 20, "right": 22},
                    ),
                ),
                stop_reason="tool_use",
            ),
            ModelResponse(text="20 + 22 = 42。", stop_reason="end_turn"),
        ]
    )
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(TextLengthTool())
    agent = Agent(model, registry)

    async for event in agent.prompt("帮我计算 20 + 22"):
        if isinstance(event, ToolStartedEvent):
            print(f"[tool:start] {event.call.name} {event.call.arguments}")
        elif isinstance(event, ToolFinishedEvent):
            print(f"[tool:end] {event.result.output}")
        elif isinstance(event, TextEvent):
            print(f"[assistant] {event.text}")
        elif isinstance(event, LoopFinishedEvent):
            print(f"[done] turns={event.total_turns}")
        elif isinstance(event, LoopFailedEvent):
            print(f"[error] {event.message}")


if __name__ == "__main__":
    asyncio.run(main())
