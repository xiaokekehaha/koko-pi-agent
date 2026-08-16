from __future__ import annotations

from collections.abc import AsyncIterator

from examples.mini_pi_agent.contracts import BeforeToolCall, LLMClient
from examples.mini_pi_agent.loop import run_agent_loop
from examples.mini_pi_agent.models import AgentEvent, AgentState, Message
from examples.mini_pi_agent.registry import ToolRegistry


class Agent:
    """A stateful shell around the stateless loop function."""

    def __init__(
        self,
        model: LLMClient,
        registry: ToolRegistry,
        *,
        before_tool_call: BeforeToolCall | None = None,
        max_turns: int = 8,
    ) -> None:
        self.state = AgentState()
        self._model = model
        self._registry = registry
        self._before_tool_call = before_tool_call
        self._max_turns = max_turns
        self._running = False

    async def prompt(self, text: str) -> AsyncIterator[AgentEvent]:
        if self._running:
            raise RuntimeError("agent is already running")
        self._running = True
        self.state.messages.append(Message(role="user", content=text))
        try:
            async for event in run_agent_loop(
                self.state,
                self._model,
                self._registry,
                before_tool_call=self._before_tool_call,
                max_turns=self._max_turns,
            ):
                yield event
        finally:
            self._running = False
