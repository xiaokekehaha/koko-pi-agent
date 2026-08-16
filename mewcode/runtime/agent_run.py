from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from mewcode.conversation import ConversationManager
from mewcode.runtime.events import EventSink, RunResult
from mewcode.runtime.run_control import (
    RunControl,
    RunControlState,
    RunInputClosedError,
    RunInputKind,
    RunInputReceipt,
    TurnReason,
)


class RunStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SETTLING = "settling"
    IDLE = "idle"


class RunCancellation:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


@dataclass(frozen=True)
class RunRequest:
    conversation: ConversationManager


class _LoopRunner(Protocol):
    """Keeps AgentRun independent from the concrete AgentLoop module."""

    async def run(
        self,
        request: RunRequest,
        emit: EventSink,
        cancellation: RunCancellation,
        run_id: str,
        control: RunControl,
    ) -> RunResult: ...


def _result_reason(result: RunResult) -> TurnReason:
    if result.status == "cancelled":
        return "cancelled"
    if result.status == "failed":
        return "failed"
    if result.status == "max_turns":
        return "max_turns"
    return "natural"


def finalize_run_result(result: RunResult, control: RunControl) -> RunResult:
    """Seal run input and attach every item that could not be delivered."""

    if control.state is RunControlState.OPEN:
        control.seal(_result_reason(result))
    undelivered = control.recover_undelivered()
    if not undelivered:
        return result
    return replace(
        result,
        undelivered_inputs=(*result.undelivered_inputs, *undelivered),
    )


class AgentRun:
    """Owns the lifecycle and queued input for one AgentLoop execution."""

    def __init__(
        self,
        loop: _LoopRunner,
        request: RunRequest,
        emit: EventSink,
        on_idle: Callable[[AgentRun], None],
    ) -> None:
        self.run_id = uuid.uuid4().hex
        self._loop = loop
        self._request = request
        self._emit = emit
        self._on_idle = on_idle
        self._cancellation = RunCancellation()
        self._control = RunControl()
        self._status = RunStatus.CREATED
        self._result: RunResult | None = None
        self._idle = asyncio.Event()
        self._task: asyncio.Task[RunResult] | None = None

    @property
    def status(self) -> RunStatus:
        return self._status

    @property
    def result(self) -> RunResult | None:
        return self._result

    def steer(self, text: str) -> RunInputReceipt:
        return self._enqueue_input(RunInputKind.STEERING, text)

    def follow_up(self, text: str) -> RunInputReceipt:
        return self._enqueue_input(RunInputKind.FOLLOW_UP, text)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("AgentRun has already started")
        self._task = asyncio.create_task(self._drive())
        self._task.add_done_callback(self._handle_task_done)

    def cancel(self) -> None:
        if self._status in (
            RunStatus.CANCELLING,
            RunStatus.SETTLING,
            RunStatus.IDLE,
        ):
            return
        self._control.seal("cancelled")
        self._cancellation.cancel()
        self._status = RunStatus.CANCELLING
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait_until_idle(self) -> RunResult:
        if self._task is None:
            raise RuntimeError("AgentRun has not started")
        await self._idle.wait()
        if self._task is not asyncio.current_task() and not self._task.cancelled():
            await asyncio.shield(self._task)
        assert self._result is not None
        return self._result

    async def _drive(self) -> RunResult:
        self._status = RunStatus.RUNNING
        try:
            self._result = await self._loop.run(
                self._request,
                self._emit,
                self._cancellation,
                self.run_id,
                self._control,
            )
        except asyncio.CancelledError:
            self._result = RunResult(status="cancelled", turns=0, final_text="")
        except Exception as exc:  # noqa: BLE001 - run boundary normalizes failures
            self._result = RunResult(
                status="failed", turns=0, final_text="", error=str(exc)
            )
        finally:
            assert self._result is not None
            self._settle(self._result)
        assert self._result is not None
        return self._result

    def _handle_task_done(self, task: asyncio.Task[RunResult]) -> None:
        if self._idle.is_set():
            return
        if task.cancelled():
            result = RunResult(status="cancelled", turns=0, final_text="")
        else:
            try:
                result = task.result()
            except Exception as exc:  # noqa: BLE001 - task boundary fallback
                result = RunResult(
                    status="failed", turns=0, final_text="", error=str(exc)
                )
        self._settle(result)

    def _settle(self, result: RunResult) -> None:
        if self._idle.is_set():
            return
        self._result = finalize_run_result(result, self._control)
        self._status = RunStatus.SETTLING
        self._on_idle(self)
        self._status = RunStatus.IDLE
        self._idle.set()

    def _enqueue_input(
        self,
        kind: RunInputKind,
        text: str,
    ) -> RunInputReceipt:
        if self._status not in (RunStatus.CREATED, RunStatus.RUNNING):
            raise RunInputClosedError(
                f"AgentRun is {self._status.value} and no longer accepts queued input"
            )
        return self._control.enqueue(kind, text)
