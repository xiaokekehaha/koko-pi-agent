"""PROTOTYPE: 一个把行分装到缓冲池页中的极小 Table Heap。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .index import RowId
from .storage import BufferPoolManager


class HeapTable:
    """每页固定放少量行，让 demo 很快触发换页和淘汰。"""

    def __init__(self, name: str, buffer_pool: BufferPoolManager, rows_per_page: int = 2) -> None:
        self.name = name
        self._buffer_pool = buffer_pool
        self._rows_per_page = rows_per_page
        self._page_ids: list[int] = []

    @property
    def page_ids(self) -> tuple[int, ...]:
        return tuple(self._page_ids)

    def insert(self, row: dict[str, Any]) -> RowId:
        if self._page_ids:
            page_id = self._page_ids[-1]
            with self._buffer_pool.fetch_page(page_id, write=True) as page:
                rows: dict[int, dict[str, Any]] = page.setdefault("rows", {})
                if len(rows) < self._rows_per_page:
                    slot = len(rows)
                    rows[slot] = deepcopy(row)
                    return page_id, slot

        guard = self._buffer_pool.new_page({"rows": {}})
        page_id = guard.page_id
        with guard as page:
            page["rows"][0] = deepcopy(row)
        self._page_ids.append(page_id)
        return page_id, 0

    def get(self, row_id: RowId) -> dict[str, Any] | None:
        page_id, slot = row_id
        with self._buffer_pool.fetch_page(page_id) as page:
            row = page.get("rows", {}).get(slot)
            return deepcopy(row) if row is not None else None

    def update(self, row_id: RowId, changes: dict[str, Any]) -> None:
        page_id, slot = row_id
        with self._buffer_pool.fetch_page(page_id, write=True) as page:
            row = page.get("rows", {}).get(slot)
            if row is None:
                raise KeyError(f"找不到 RowId {row_id}")
            row.update(deepcopy(changes))

    def scan(self) -> list[tuple[RowId, dict[str, Any]]]:
        result: list[tuple[RowId, dict[str, Any]]] = []
        for page_id in self._page_ids:
            with self._buffer_pool.fetch_page(page_id) as page:
                for slot, row in sorted(page.get("rows", {}).items()):
                    result.append(((page_id, slot), deepcopy(row)))
        return result
