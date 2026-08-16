from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from typing import Any

from examples.mini_pi_agent.models import Message, ModelResponse


class ScriptedLLMClient:
    """Returns predefined responses so tests never need an API key."""

    def __init__(self, responses: Iterable[ModelResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[tuple[tuple[Message, ...], tuple[dict[str, Any], ...]]] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:
        self.requests.append((tuple(messages), tuple(tools)))
        if not self._responses:
            raise RuntimeError("scripted LLM has no response left")
        return self._responses.popleft()
