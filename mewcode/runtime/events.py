from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, TypeAlias

from mewcode.context import CompactBoundary


class PermissionResponse(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"


@dataclass(frozen=True)
class RunResult:
    status: Literal["completed", "cancelled", "failed", "max_turns"]
    turns: int
    final_text: str
    error: str = ""


@dataclass(frozen=True)
class RunStarted:
    run_id: str


@dataclass(frozen=True)
class RunFinished:
    run_id: str
    result: RunResult


@dataclass(frozen=True)
class RunFailed:
    run_id: str
    message: str


@dataclass(frozen=True)
class TurnStarted:
    turn: int


@dataclass(frozen=True)
class MessageStarted:
    turn: int


@dataclass(frozen=True)
class MessageFinished:
    turn: int
    text: str
    stop_reason: str


@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_id: str
    tool_name: str


@dataclass
class StreamText:
    text: str


@dataclass
class ThinkingText:
    text: str


@dataclass
class RetryEvent:
    reason: str
    wait: float = 0.0


@dataclass
class ToolUseEvent:
    tool_name: str
    tool_id: str
    arguments: dict[str, Any]


@dataclass
class ToolResultEvent:
    tool_id: str
    tool_name: str
    output: str
    is_error: bool
    elapsed: float


# The canonical completion name and the compatibility event are the same
# object.  Adapters therefore do not receive duplicate semantic events.
ToolExecutionFinished = ToolResultEvent


@dataclass
class TurnComplete:
    turn: int


TurnFinished = TurnComplete


@dataclass
class LoopComplete:
    total_turns: int


@dataclass
class UsageEvent:
    input_tokens: int
    output_tokens: int


UsageUpdated = UsageEvent


@dataclass
class ErrorEvent:
    message: str


@dataclass
class CompactNotification:
    before_tokens: int
    message: str
    boundary: CompactBoundary | None = None


@dataclass
class HookEvent:
    hook_id: str
    event: str
    output: str
    success: bool


@dataclass
class PermissionRequest:
    tool_name: str
    description: str
    future: asyncio.Future[PermissionResponse]


PermissionRequested = PermissionRequest
RetryScheduled = RetryEvent
CompactionFinished = CompactNotification


AgentEvent: TypeAlias = (
    RunStarted
    | RunFinished
    | RunFailed
    | TurnStarted
    | MessageStarted
    | MessageFinished
    | ToolExecutionStarted
    | StreamText
    | ThinkingText
    | RetryEvent
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | LoopComplete
    | UsageEvent
    | ErrorEvent
    | PermissionRequest
    | CompactNotification
    | HookEvent
)

EventSink: TypeAlias = Callable[[AgentEvent], Awaitable[None]]
