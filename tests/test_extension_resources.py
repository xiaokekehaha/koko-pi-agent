from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager

import pytest

from koko_pi_agent.extensions import (
    ExtensionDiagnostic,
    ResourceScope,
    ResourceScopeStateError,
)


def _make_scope(
    diagnostics: list[ExtensionDiagnostic] | None = None,
    *,
    cancel_timeout: float = 5.0,
) -> tuple[ResourceScope, list[ExtensionDiagnostic]]:
    sink: list[ExtensionDiagnostic] = [] if diagnostics is None else diagnostics
    scope = ResourceScope(
        extension_id="test.extension",
        source="builtin",
        diagnostics=sink.append,
        cancel_timeout=cancel_timeout,
    )
    return scope, sink


@pytest.mark.asyncio
async def test_acquire_handles_sync_and_async_context_managers() -> None:
    events: list[str] = []

    @contextmanager
    def sync_resource():
        events.append("sync-enter")
        yield "sync-value"
        events.append("sync-exit")

    @asynccontextmanager
    async def async_resource():
        events.append("async-enter")
        yield "async-value"
        events.append("async-exit")

    scope, _ = _make_scope()
    assert await scope.acquire("sync", sync_resource()) == "sync-value"
    assert await scope.acquire("async", async_resource()) == "async-value"
    assert events == ["sync-enter", "async-enter"]

    assert await scope.aclose() == []
    # 逆序：后获取的 async 先释放
    assert events == ["sync-enter", "async-enter", "async-exit", "sync-exit"]


@pytest.mark.asyncio
async def test_defer_accepts_sync_and_async_cleanup() -> None:
    closed: list[str] = []

    async def async_cleanup() -> None:
        closed.append("async")

    scope, _ = _make_scope()
    scope.defer("sync", lambda: closed.append("sync"))
    scope.defer("async", async_cleanup)

    assert await scope.aclose() == []
    assert closed == ["async", "sync"]


@pytest.mark.asyncio
async def test_close_order_is_contribution_then_task_then_resource() -> None:
    order: list[str] = []
    started = asyncio.Event()

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            order.append("task")
            raise

    scope, _ = _make_scope()
    scope.defer("resource", lambda: order.append("resource"))
    scope.add_contribution("tool", lambda: order.append("contribution"))
    scope.start_task("forever", forever())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    assert await scope.aclose() == []
    assert order == ["contribution", "task", "resource"]


@pytest.mark.asyncio
async def test_resources_close_in_reverse_registration_order() -> None:
    order: list[int] = []

    scope, _ = _make_scope()
    for index in range(4):
        scope.defer(f"resource-{index}", lambda index=index: order.append(index))

    assert await scope.aclose() == []
    assert order == [3, 2, 1, 0]


@pytest.mark.asyncio
async def test_one_cleanup_failure_does_not_stop_the_rest() -> None:
    closed: list[str] = []

    def boom() -> None:
        raise RuntimeError("cleanup exploded")

    scope, sink = _make_scope()
    scope.defer("first", lambda: closed.append("first"))
    scope.defer("broken", boom)
    scope.defer("last", lambda: closed.append("last"))

    failures = await scope.aclose()

    assert closed == ["last", "first"]
    assert len(failures) == 1
    assert failures[0].name == "broken"
    assert failures[0].kind == "resource"
    assert isinstance(failures[0].error, RuntimeError)
    assert "cleanup exploded" in failures[0].describe()

    statuses = [item.status for item in sink]
    assert statuses == ["cleanup_failed"]
    assert sink[0].name == "broken"
    assert sink[0].phase == "closing"


@pytest.mark.asyncio
async def test_failed_task_records_diagnostic_and_consumes_exception() -> None:
    async def explode() -> None:
        raise ValueError("task exploded")

    scope, sink = _make_scope()
    handle = scope.start_task("exploding", explode())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert handle.done is True
    assert handle.status == "failed"

    failed = [item for item in sink if item.status == "task_failed"]
    assert len(failed) == 1
    assert failed[0].name == "exploding"
    assert failed[0].kind == "task"
    assert "task exploded" in failed[0].error

    # 关闭时不再重复报告已完成的失败任务
    assert await scope.aclose() == []


@pytest.mark.asyncio
async def test_running_task_is_cancelled_on_close() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    scope, sink = _make_scope()
    handle = scope.start_task("forever", forever())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert handle.status == "running"

    assert await scope.aclose() == []
    assert cancelled.is_set()
    assert handle.status == "cancelled"
    assert [item for item in sink if item.status == "task_failed"] == []


@pytest.mark.asyncio
async def test_task_ignoring_cancellation_times_out_and_is_reported() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def stubborn() -> None:
        started.set()
        while not release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                # 故意吞掉取消，模拟不响应取消的协程
                continue

    scope, sink = _make_scope(cancel_timeout=0.05)
    scope.start_task("stubborn", stubborn())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    failures = await scope.aclose()

    assert len(failures) == 1
    assert failures[0].kind == "task"
    assert failures[0].name == "stubborn"
    assert isinstance(failures[0].error, TimeoutError)

    timeouts = [item for item in sink if item.status == "task_cancel_timeout"]
    assert len(timeouts) == 1
    assert timeouts[0].name == "stubborn"

    # 关闭已返回，不被这个任务无限阻塞；随后放行让事件循环收干净
    release.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_close_is_idempotent_and_runs_cleanup_once() -> None:
    calls: list[str] = []

    scope, _ = _make_scope()
    scope.defer("once", lambda: calls.append("cleanup"))

    assert await scope.aclose() == []
    assert await scope.aclose() == []
    assert calls == ["cleanup"]
    assert scope.state == "closed"


@pytest.mark.asyncio
async def test_concurrent_close_runs_cleanup_once() -> None:
    calls: list[str] = []

    async def slow_cleanup() -> None:
        await asyncio.sleep(0.01)
        calls.append("cleanup")

    scope, _ = _make_scope()
    scope.defer("slow", slow_cleanup)

    results = await asyncio.gather(scope.aclose(), scope.aclose())

    assert calls == ["cleanup"]
    assert results == [[], []]


@pytest.mark.asyncio
async def test_cleanup_failure_still_reaches_closed_state() -> None:
    def boom() -> None:
        raise RuntimeError("nope")

    scope, _ = _make_scope()
    scope.defer("broken", boom)

    failures = await scope.aclose()

    assert len(failures) == 1
    assert scope.state == "closed"


@pytest.mark.asyncio
async def test_registration_after_close_is_rejected() -> None:
    scope, _ = _make_scope()
    await scope.aclose()

    with pytest.raises(ResourceScopeStateError):
        scope.defer("late", lambda: None)
    with pytest.raises(ResourceScopeStateError):
        scope.add_contribution("late", lambda: None)
    with pytest.raises(ResourceScopeStateError):
        await scope.acquire("late", None)

    late_coroutine = asyncio.sleep(0)
    try:
        with pytest.raises(ResourceScopeStateError):
            scope.start_task("late", late_coroutine)
    finally:
        # 被拒绝的 coroutine 由调用方负责收尾，否则留下 never-awaited 警告
        late_coroutine.close()


@pytest.mark.asyncio
async def test_acquire_rejects_non_context_manager() -> None:
    scope, _ = _make_scope()

    with pytest.raises(TypeError):
        await scope.acquire("plain", object())

    assert await scope.aclose() == []


@pytest.mark.asyncio
async def test_failed_acquire_does_not_register_cleanup() -> None:
    closed: list[str] = []

    @contextmanager
    def broken_resource():
        raise RuntimeError("enter failed")
        yield  # pragma: no cover

    scope, _ = _make_scope()
    with pytest.raises(RuntimeError):
        await scope.acquire("broken", broken_resource())

    assert await scope.aclose() == []
    assert closed == []


@pytest.mark.asyncio
async def test_task_failure_and_cleanup_failure_are_both_reported() -> None:
    async def explode() -> None:
        raise ValueError("task exploded")

    def boom() -> None:
        raise RuntimeError("cleanup exploded")

    scope, sink = _make_scope()
    scope.start_task("exploding", explode())
    scope.defer("broken", boom)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    failures = await scope.aclose()

    # 已结束的失败任务只留诊断，不再计入清理失败；cleanup 失败照常聚合
    assert [failure.name for failure in failures] == ["broken"]
    assert [item.status for item in sink] == ["task_failed", "cleanup_failed"]
    assert scope.state == "closed"
