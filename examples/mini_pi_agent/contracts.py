from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, TypeAlias

from pydantic import BaseModel

from examples.mini_pi_agent.models import (
    Message,
    ModelResponse,
    PermissionDecision,
    ToolCall,
    ToolResult,
)


class LLMClient(Protocol):
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse: ...


class Tool(Protocol):
    name: str
    description: str
    params_model: type[BaseModel]

    async def execute(self, params: BaseModel) -> ToolResult: ...


BeforeToolCall: TypeAlias = Callable[
    [ToolCall, Tool], Awaitable[PermissionDecision]
]
