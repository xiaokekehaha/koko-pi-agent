"""PROTOTYPE: P4 独占行锁、等待队列和 waits-for 死锁检测。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Condition, RLock
from typing import Any


class TransactionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class TransactionAborted(RuntimeError):
    pass


@dataclass
class LockRequest:
    txn_id: int
    granted: bool = False


class LockManager:
    """教学版严格两阶段锁：写事务持有 X 锁直到提交或回滚。"""

    def __init__(self) -> None:
        self._queues: dict[str, list[LockRequest]] = {}
        self._status: dict[int, TransactionStatus] = {}
        self._mutex = RLock()
        self._changed = Condition(self._mutex)

    def begin(self, txn_id: int) -> None:
        with self._changed:
            self._status[txn_id] = TransactionStatus.ACTIVE

    def acquire_exclusive(self, txn_id: int, resource: str) -> None:
        with self._changed:
            if self._status.get(txn_id) is TransactionStatus.ABORTED:
                raise TransactionAborted(f"事务 T{txn_id} 已回滚")

            queue = self._queues.setdefault(resource, [])
            request = LockRequest(txn_id)
            queue.append(request)

            while True:
                if self._status.get(txn_id) is TransactionStatus.ABORTED:
                    raise TransactionAborted(f"事务 T{txn_id} 被死锁检测器回滚")
                blockers = self._blockers(queue, request)
                if not blockers:
                    request.granted = True
                    self._status[txn_id] = TransactionStatus.ACTIVE
                    return
                self._status[txn_id] = TransactionStatus.WAITING
                self._changed.wait()

    def _blockers(self, queue: list[LockRequest], request: LockRequest) -> set[int]:
        blockers: set[int] = set()
        for queued in queue:
            if queued is request:
                break
            if queued.txn_id != request.txn_id:
                blockers.add(queued.txn_id)
        for queued in queue:
            if queued.granted and queued.txn_id != request.txn_id:
                blockers.add(queued.txn_id)
        return blockers

    def release_all(self, txn_id: int, *, commit: bool = True) -> None:
        with self._changed:
            for resource in list(self._queues):
                queue = self._queues[resource]
                queue[:] = [
                    request
                    for request in queue
                    if request.txn_id != txn_id
                ]
                if not queue:
                    del self._queues[resource]
            if self._status.get(txn_id) is not TransactionStatus.ABORTED:
                self._status[txn_id] = (
                    TransactionStatus.COMMITTED if commit else TransactionStatus.ABORTED
                )
            self._changed.notify_all()

    def waits_for_graph(self) -> dict[int, set[int]]:
        with self._changed:
            return self._waits_for_graph_locked()

    def _waits_for_graph_locked(self) -> dict[int, set[int]]:
        graph: dict[int, set[int]] = {
            txn_id: set()
            for txn_id, status in self._status.items()
            if status not in {TransactionStatus.COMMITTED, TransactionStatus.ABORTED}
        }
        for queue in self._queues.values():
            for request in queue:
                if request.granted:
                    continue
                graph.setdefault(request.txn_id, set()).update(
                    self._blockers(queue, request)
                )
        return graph

    def detect_deadlock(self) -> list[int] | None:
        with self._changed:
            return self._find_cycle(self._waits_for_graph_locked())

    def abort_youngest_in_cycle(self) -> int | None:
        with self._changed:
            cycle = self._find_cycle(self._waits_for_graph_locked())
            if not cycle:
                return None
            victim = max(cycle)
            self._status[victim] = TransactionStatus.ABORTED
            for resource in list(self._queues):
                queue = self._queues[resource]
                queue[:] = [
                    request
                    for request in queue
                    if request.txn_id != victim
                ]
                if not queue:
                    del self._queues[resource]
            self._changed.notify_all()
            return victim

    @staticmethod
    def _find_cycle(graph: dict[int, set[int]]) -> list[int] | None:
        visited: set[int] = set()
        active: set[int] = set()
        path: list[int] = []

        def visit(txn_id: int) -> list[int] | None:
            if txn_id in active:
                return path[path.index(txn_id) :]
            if txn_id in visited:
                return None
            active.add(txn_id)
            path.append(txn_id)
            for blocker in graph.get(txn_id, set()):
                cycle = visit(blocker)
                if cycle:
                    return cycle
            path.pop()
            active.remove(txn_id)
            visited.add(txn_id)
            return None

        for txn_id in graph:
            cycle = visit(txn_id)
            if cycle:
                return cycle
        return None

    def snapshot(self) -> dict[str, Any]:
        with self._changed:
            return {
                "status": {
                    f"T{txn_id}": status.value
                    for txn_id, status in sorted(self._status.items())
                },
                "queues": {
                    resource: [
                        {"txn": f"T{request.txn_id}", "granted": request.granted}
                        for request in queue
                    ]
                    for resource, queue in sorted(self._queues.items())
                },
                "waits_for": {
                    f"T{txn_id}": [f"T{other}" for other in sorted(blockers)]
                    for txn_id, blockers in sorted(
                        self._waits_for_graph_locked().items()
                    )
                },
            }
