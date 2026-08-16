from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeAlias


class RunInputKind(Enum):
    STEERING = "steering"
    FOLLOW_UP = "follow_up"


class RunControlState(Enum):
    OPEN = "open"
    SEALED = "sealed"


TurnReason: TypeAlias = Literal[
    "tool_calls",
    "steering",
    "follow_up",
    "natural",
    "retry",
    "terminate",
    "max_turns",
    "cancelled",
    "failed",
]
HardStopReason: TypeAlias = Literal["terminate", "cancelled", "failed"]


@dataclass(frozen=True)
class QueuedRunInput:
    input_id: str
    kind: RunInputKind
    text: str


@dataclass(frozen=True)
class RunInputReceipt:
    item: QueuedRunInput
    position: int


@dataclass(frozen=True)
class TurnDirective:
    continue_run: bool
    deliveries: tuple[QueuedRunInput, ...]
    reason: TurnReason


class RunInputClosedError(RuntimeError):
    pass


@dataclass(frozen=True)
class _QueuedRecord:
    sequence: int
    item: QueuedRunInput


class RunControl:
    """Owns queued input and turn-boundary decisions for one AgentRun."""

    def __init__(self) -> None:
        self._state = RunControlState.OPEN
        self._steering: deque[_QueuedRecord] = deque()
        self._follow_up: deque[_QueuedRecord] = deque()
        self._next_sequence = 0
        self._sealed_reason: TurnReason = "natural"

    @property
    def state(self) -> RunControlState:
        return self._state

    @property
    def pending_count(self) -> int:
        return len(self._steering) + len(self._follow_up)

    def enqueue(self, kind: RunInputKind, text: str) -> RunInputReceipt:
        if self._state is RunControlState.SEALED:
            raise RunInputClosedError("AgentRun no longer accepts queued input")
        if not text.strip():
            raise ValueError("Queued run input must not be empty")

        item = QueuedRunInput(
            input_id=uuid.uuid4().hex,
            kind=kind,
            text=text,
        )
        record = _QueuedRecord(sequence=self._next_sequence, item=item)
        self._next_sequence += 1
        queue = self._queue_for(kind)
        queue.append(record)
        return RunInputReceipt(item=item, position=len(queue))

    def before_first_turn(self) -> tuple[QueuedRunInput, ...]:
        if self._state is RunControlState.SEALED:
            return ()
        return self._drain(self._steering)

    def after_turn(
        self,
        *,
        would_stop: bool,
        hard_stop: HardStopReason | None = None,
        continuation_allowed: bool = True,
        continue_reason: Literal["tool_calls", "retry"] = "tool_calls",
    ) -> TurnDirective:
        if self._state is RunControlState.SEALED:
            return TurnDirective(False, (), self._sealed_reason)

        if hard_stop is not None:
            self.seal(hard_stop)
            return TurnDirective(False, (), hard_stop)

        if not continuation_allowed:
            if would_stop and self.pending_count == 0:
                self.seal("natural")
                return TurnDirective(False, (), "natural")
            self.seal("max_turns")
            return TurnDirective(False, (), "max_turns")

        steering = self._drain(self._steering)
        if steering:
            return TurnDirective(True, steering, "steering")

        if not would_stop:
            return TurnDirective(True, (), continue_reason)

        follow_up = self._drain(self._follow_up)
        if follow_up:
            return TurnDirective(True, follow_up, "follow_up")

        self.seal("natural")
        return TurnDirective(False, (), "natural")

    def seal(self, reason: TurnReason) -> None:
        if self._state is RunControlState.SEALED:
            return
        self._sealed_reason = reason
        self._state = RunControlState.SEALED

    def recover_undelivered(self) -> tuple[QueuedRunInput, ...]:
        if self._state is RunControlState.OPEN:
            self.seal("failed")
        records = sorted(
            (*self._steering, *self._follow_up),
            key=lambda record: record.sequence,
        )
        self._steering.clear()
        self._follow_up.clear()
        return tuple(record.item for record in records)

    def _queue_for(self, kind: RunInputKind) -> deque[_QueuedRecord]:
        if kind is RunInputKind.STEERING:
            return self._steering
        if kind is RunInputKind.FOLLOW_UP:
            return self._follow_up
        raise ValueError(f"Unsupported run input kind: {kind!r}")

    @staticmethod
    def _drain(queue: deque[_QueuedRecord]) -> tuple[QueuedRunInput, ...]:
        items = tuple(record.item for record in queue)
        queue.clear()
        return items
