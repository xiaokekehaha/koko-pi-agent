from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False


@dataclass(frozen=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: Literal["tool_use", "end_turn"] = "end_turn"


@dataclass(frozen=True)
class ToolResult:
    output: str
    is_error: bool = False


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> PermissionDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> PermissionDecision:
        return cls(allowed=False, reason=reason)


@dataclass(frozen=True)
class TextEvent:
    text: str


@dataclass(frozen=True)
class ToolStartedEvent:
    call: ToolCall


@dataclass(frozen=True)
class ToolFinishedEvent:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class LoopFinishedEvent:
    final_text: str
    total_turns: int


@dataclass(frozen=True)
class LoopFailedEvent:
    message: str
    total_turns: int


AgentEvent: TypeAlias = (
    TextEvent
    | ToolStartedEvent
    | ToolFinishedEvent
    | LoopFinishedEvent
    | LoopFailedEvent
)


@dataclass
class AgentState:
    messages: list[Message] = field(default_factory=list)
