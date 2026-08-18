"""PROTOTYPE: 一次运行观察 MiniDB 的四层状态变化。

运行：uv run python -m examples.minidb_prototype.demo
"""

from __future__ import annotations

import json
import time
from threading import Barrier, Lock, Thread
from typing import Any

from .concurrency import LockManager, TransactionAborted
from .execution import Predicate, Query, QueryEngine
from .index import BPlusTree
from .storage import BufferPoolManager, InMemoryDiskManager
from .table import HeapTable


def show(title: str, value: Any) -> None:
    print(f"\n{title}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def heading(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def build_storage_and_table() -> tuple[BufferPoolManager, HeapTable, list[tuple[int, tuple[int, int]]]]:
    heading("P1：缓冲池像只有 3 张桌子的档案室")
    disk = InMemoryDiskManager()
    buffer_pool = BufferPoolManager(disk, pool_size=3, k=2)
    table = HeapTable("users", buffer_pool, rows_per_page=2)

    users = [
        {"id": 5, "name": "小周", "age": 29, "city": "深圳"},
        {"id": 2, "name": "阿宁", "age": 35, "city": "上海"},
        {"id": 8, "name": "小雨", "age": 24, "city": "杭州"},
        {"id": 1, "name": "老陈", "age": 41, "city": "北京"},
        {"id": 3, "name": "小林", "age": 31, "city": "广州"},
        {"id": 7, "name": "阿青", "age": 38, "city": "成都"},
        {"id": 9, "name": "小叶", "age": 27, "city": "武汉"},
    ]

    locations: list[tuple[int, tuple[int, int]]] = []
    for user in users:
        row_id = table.insert(user)
        locations.append((user["id"], row_id))
        state = buffer_pool.snapshot()
        show(
            f"插入 id={user['id']} -> RowId={row_id} 后",
            {
                "frames": state["frames"],
                "lru_k": state["lru_k"],
            },
        )

    buffer_pool.flush_all()
    show(
        "P1 最终状态：注意 pin_count 全为 0，说明 PageGuard 自动配平",
        buffer_pool.snapshot(),
    )
    return buffer_pool, table, locations


def build_index(
    table: HeapTable, locations: list[tuple[int, tuple[int, int]]]
) -> BPlusTree:
    heading("P2：B+ 树像商场导览牌，内部节点指路，叶子节点放 RowId")
    index = BPlusTree(max_keys=3)
    for key, row_id in locations:
        index.insert(key, row_id)
        show(f"插入索引键 {key} 后", index.snapshot())

    row_id = index.search(7)
    show("点查 id=7", {"row_id": row_id, "row": table.get(row_id) if row_id else None})
    show(
        "范围查找 3 <= id <= 8（沿叶子 next 指针走）",
        [
            {"id": key, "row_id": row_id, "name": table.get(row_id)["name"]}
            for key, row_id in index.range_scan(3, 8)
        ],
    )
    return index


def run_queries(table: HeapTable, index: BPlusTree) -> None:
    heading("P3：执行器像流水线，优化器负责换一条更省事的流水线")
    engine = QueryEngine(table, index)

    point_query = Query(
        predicate=Predicate("id", "=", 7),
        columns=("id", "name", "age"),
    )
    point_result = engine.execute(point_query)
    show(
        "查询一：SELECT id, name, age FROM users WHERE id = 7",
        {
            "raw_plan": point_result.raw_plan,
            "optimized_plan": point_result.optimized_plan,
            "stats": point_result.stats,
            "rows": point_result.rows,
        },
    )

    top_query = Query(
        predicate=Predicate("age", ">=", 30),
        columns=("name", "age"),
        order_by=("age", True),
        limit=3,
    )
    top_result = engine.execute(top_query)
    show(
        "查询二：筛选 30 岁以上用户，并取年龄最大的 3 位",
        {
            "raw_plan": top_result.raw_plan,
            "optimized_plan": top_result.optimized_plan,
            "stats": top_result.stats,
            "rows": top_result.rows,
        },
    )


def run_deadlock_case() -> None:
    heading("P4：两个事务各拿一把钥匙，再等待对方手里的钥匙")
    lock_manager = LockManager()
    both_hold_first_lock = Barrier(2)
    event_lock = Lock()
    events: list[str] = []

    def record(message: str) -> None:
        with event_lock:
            events.append(message)

    def transaction(txn_id: int, first: str, second: str) -> None:
        lock_manager.begin(txn_id)
        try:
            lock_manager.acquire_exclusive(txn_id, first)
            record(f"T{txn_id} 已拿到 {first}")
            both_hold_first_lock.wait()
            record(f"T{txn_id} 请求 {second}")
            lock_manager.acquire_exclusive(txn_id, second)
            record(f"T{txn_id} 已拿到 {second}")
            lock_manager.release_all(txn_id, commit=True)
            record(f"T{txn_id} 提交并释放全部锁")
        except TransactionAborted as exc:
            record(str(exc))

    threads = [
        Thread(target=transaction, args=(1, "row:A", "row:B"), daemon=True),
        Thread(target=transaction, args=(2, "row:B", "row:A"), daemon=True),
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + 2
    cycle = lock_manager.detect_deadlock()
    while cycle is None and time.monotonic() < deadline:
        time.sleep(0.01)
        cycle = lock_manager.detect_deadlock()
    if cycle is None:
        raise RuntimeError("预期的死锁没有形成")

    show("检测到环：T1 等 T2，T2 又等 T1", lock_manager.snapshot())
    victim = lock_manager.abort_youngest_in_cycle()
    show("回滚较年轻的事务，打破环", {"victim": f"T{victim}"})

    for thread in threads:
        thread.join(timeout=2)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("死锁解除后仍有事务线程未退出")

    show("P4 最终状态", {"events": events, "locks": lock_manager.snapshot()})


def main() -> None:
    _, table, locations = build_storage_and_table()
    index = build_index(table, locations)
    run_queries(table, index)
    run_deadlock_case()

    heading("完成：四个项目不是四座孤岛，而是一条从页到 SQL 的调用链")
    print("继续阅读：docs/python-minidb-learning-guide.md")


if __name__ == "__main__":
    main()
