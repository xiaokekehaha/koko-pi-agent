"""Extension 资源与受控后台任务的所有权实现。

一个 ExtensionDefinition 的每次激活对应一个 ResourceScope。Scope 内部维护
contribution、task、resource 三类账本，关闭时按"撤销 contribution -> 取消并等待
task -> 逆序释放 resource"执行：能力不可再进入后，后台逻辑才停止，底层连接或
文件才释放。

单个清理失败不会中断其余清理；全部失败以 ExtensionCleanupFailure 列表返回，由
ExtensionSession 汇总成一个 ExtensionCloseError。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from koko_pi_agent.extensions.contracts import (
    ExtensionCleanupFailure,
    ExtensionDiagnostic,
    ExtensionTaskHandle,
)

T = TypeVar("T")

CleanupCallable = Callable[[], object]
DiagnosticSink = Callable[[ExtensionDiagnostic], None]

DEFAULT_CANCEL_TIMEOUT = 5.0

CONTRIBUTION = "contribution"
RESOURCE = "resource"
TASK = "task"


class ResourceScopeStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class _LedgerEntry:
    kind: str
    name: str
    sequence: int
    cleanup: CleanupCallable


@dataclass
class _TaskRecord:
    name: str
    sequence: int
    task: asyncio.Task[None]
    handle: ExtensionTaskHandle


async def _run_cleanup(cleanup: CleanupCallable) -> None:
    """同一个入口处理同步与异步 cleanup，调用方不必区分两套 Interface。"""

    result = cleanup()
    if inspect.isawaitable(result):
        await result


class TaskSupervisor:
    """只监护通过 ExtensionAPI.start_task() 创建的任务。

    done callback 必须读取 exception()，否则失败任务会留下
    "Task exception was never retrieved" 且没有任何诊断。
    """

    def __init__(
        self,
        *,
        extension_id: str,
        source: str,
        diagnostics: DiagnosticSink,
        cancel_timeout: float = DEFAULT_CANCEL_TIMEOUT,
    ) -> None:
        self._extension_id = extension_id
        self._source = source
        self._diagnostics = diagnostics
        self._cancel_timeout = cancel_timeout
        self._records: list[_TaskRecord] = []
        self._next_sequence = 1

    @property
    def active_count(self) -> int:
        return sum(1 for record in self._records if not record.task.done())

    def start(self, name: str, awaitable: Awaitable[None]) -> ExtensionTaskHandle:
        task: asyncio.Task[None] = asyncio.ensure_future(awaitable)
        handle = ExtensionTaskHandle(
            extension_id=self._extension_id,
            name=name,
            task=task,
        )
        record = _TaskRecord(
            name=name,
            sequence=self._next_sequence,
            task=task,
            handle=handle,
        )
        self._next_sequence += 1
        self._records.append(record)
        task.add_done_callback(functools.partial(self._on_task_done, name))
        return handle

    def _on_task_done(self, name: str, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        self._diagnostics(
            ExtensionDiagnostic(
                extension_id=self._extension_id,
                source=self._source,
                status="task_failed",
                error=str(error),
                kind=TASK,
                name=name,
                phase="running",
            )
        )

    async def shutdown(self) -> list[ExtensionCleanupFailure]:
        """取消全部未完成任务并在统一超时内等待。

        用一次 asyncio.wait 而不是逐个 wait_for：后者在协程吞掉取消时会把总等待
        时间乘以任务数。
        """

        failures: list[ExtensionCleanupFailure] = []
        pending = [record for record in self._records if not record.task.done()]
        if not pending:
            return failures

        for record in pending:
            record.task.cancel()

        _, still_pending = await asyncio.wait(
            [record.task for record in pending],
            timeout=self._cancel_timeout,
        )

        for record in pending:
            if record.task not in still_pending:
                continue
            # 保留引用与 done callback：Python 无法强制终止一个吞掉取消的协程，
            # 只能如实报告，不阻塞剩余清理。
            error = TimeoutError(
                f"task '{record.name}' ignored cancellation for "
                f"{self._cancel_timeout}s"
            )
            self._diagnostics(
                ExtensionDiagnostic(
                    extension_id=self._extension_id,
                    source=self._source,
                    status="task_cancel_timeout",
                    error=str(error),
                    kind=TASK,
                    name=record.name,
                    phase="closing",
                )
            )
            failures.append(
                ExtensionCleanupFailure(
                    extension_id=self._extension_id,
                    source=self._source,
                    kind=TASK,
                    name=record.name,
                    error=error,
                )
            )
        return failures


class ResourceScope:
    def __init__(
        self,
        *,
        extension_id: str,
        source: str,
        diagnostics: DiagnosticSink,
        cancel_timeout: float = DEFAULT_CANCEL_TIMEOUT,
    ) -> None:
        self._extension_id = extension_id
        self._source = source
        self._diagnostics = diagnostics
        self._entries: list[_LedgerEntry] = []
        self._supervisor = TaskSupervisor(
            extension_id=extension_id,
            source=source,
            diagnostics=diagnostics,
            cancel_timeout=cancel_timeout,
        )
        self._next_sequence = 1
        self._state = "open"
        self._close_lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def extension_id(self) -> str:
        return self._extension_id

    def add_contribution(self, name: str, cleanup: CleanupCallable) -> None:
        """登记一条能力贡献的撤销动作（当前是 Tool RegistrationHandle.close）。"""

        self._append(CONTRIBUTION, name, cleanup)

    def defer(self, name: str, cleanup: CleanupCallable) -> None:
        self._append(RESOURCE, name, cleanup)

    async def acquire(self, name: str, manager: Any) -> Any:
        self._ensure_open()
        if hasattr(manager, "__aenter__"):
            value = await manager.__aenter__()

            def close_async() -> Any:
                return manager.__aexit__(None, None, None)

            self._append(RESOURCE, name, close_async)
            return value

        if not hasattr(manager, "__enter__"):
            raise TypeError(
                f"acquire('{name}') requires a context manager, got "
                f"{type(manager).__name__}"
            )
        value = manager.__enter__()

        def close_sync() -> Any:
            return manager.__exit__(None, None, None)

        self._append(RESOURCE, name, close_sync)
        return value

    def start_task(self, name: str, awaitable: Awaitable[None]) -> ExtensionTaskHandle:
        self._ensure_open()
        return self._supervisor.start(name, awaitable)

    async def aclose(self) -> list[ExtensionCleanupFailure]:
        """幂等关闭。第一次调用无论成败都进入 closed，重复调用返回空列表。

        锁是必须的：清理过程有 await 点，没有它并发的第二个调用会看到 "closing"
        并把每个 cleanup 跑第二遍。
        """

        if self._state == "closed":
            return []
        async with self._close_lock:
            if self._state == "closed":
                return []
            self._state = "closing"
            failures: list[ExtensionCleanupFailure] = []
            try:
                failures.extend(await self._close_kind(CONTRIBUTION))
                failures.extend(await self._supervisor.shutdown())
                failures.extend(await self._close_kind(RESOURCE))
            finally:
                self._entries.clear()
                self._state = "closed"
            return failures

    async def _close_kind(self, kind: str) -> list[ExtensionCleanupFailure]:
        failures: list[ExtensionCleanupFailure] = []
        selected = [entry for entry in self._entries if entry.kind == kind]
        for entry in sorted(selected, key=lambda item: item.sequence, reverse=True):
            try:
                await _run_cleanup(entry.cleanup)
            except Exception as error:
                self._diagnostics(
                    ExtensionDiagnostic(
                        extension_id=self._extension_id,
                        source=self._source,
                        status="cleanup_failed",
                        error=str(error),
                        kind=entry.kind,
                        name=entry.name,
                        phase="closing",
                    )
                )
                failures.append(
                    ExtensionCleanupFailure(
                        extension_id=self._extension_id,
                        source=self._source,
                        kind=entry.kind,
                        name=entry.name,
                        error=error,
                    )
                )
        return failures

    def _append(self, kind: str, name: str, cleanup: CleanupCallable) -> None:
        self._ensure_open()
        self._entries.append(
            _LedgerEntry(
                kind=kind,
                name=name,
                sequence=self._next_sequence,
                cleanup=cleanup,
            )
        )
        self._next_sequence += 1

    def _ensure_open(self) -> None:
        if self._state != "open":
            raise ResourceScopeStateError(
                f"ResourceScope of '{self._extension_id}' is {self._state}"
            )
