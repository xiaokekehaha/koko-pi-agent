"""PROTOTYPE: P3 查询执行器与两条看得见的规则优化。"""

from __future__ import annotations

from dataclasses import dataclass
from operator import eq, ge, gt, le, lt, ne
from typing import Any, Callable

from .index import BPlusTree
from .table import HeapTable


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "=": eq,
    "!=": ne,
    ">": gt,
    ">=": ge,
    "<": lt,
    "<=": le,
}


@dataclass(frozen=True)
class Predicate:
    column: str
    operator: str
    value: Any

    def matches(self, row: dict[str, Any]) -> bool:
        return _OPERATORS[self.operator](row[self.column], self.value)

    def __str__(self) -> str:
        return f"{self.column} {self.operator} {self.value!r}"


@dataclass(frozen=True)
class Query:
    predicate: Predicate | None = None
    columns: tuple[str, ...] = ()
    order_by: tuple[str, bool] | None = None  # (column, descending)
    limit: int | None = None


@dataclass(frozen=True)
class QueryResult:
    raw_plan: str
    optimized_plan: str
    rows: list[dict[str, Any]]
    stats: dict[str, int]


class QueryEngine:
    """不解析 SQL，只执行已经结构化的 Query。"""

    def __init__(self, table: HeapTable, primary_key_index: BPlusTree) -> None:
        self._table = table
        self._index = primary_key_index

    def execute(self, query: Query) -> QueryResult:
        raw_plan = self._raw_plan(query)
        use_index = (
            query.predicate is not None
            and query.predicate.column == "id"
            and query.predicate.operator == "="
        )

        if use_index:
            row_id = self._index.search(int(query.predicate.value))
            row = self._table.get(row_id) if row_id is not None else None
            candidates = [row] if row is not None else []
            rows_examined = len(candidates)
        else:
            scanned = self._table.scan()
            candidates = [row for _, row in scanned]
            rows_examined = len(candidates)

        if query.predicate is not None:
            candidates = [row for row in candidates if query.predicate.matches(row)]
        rows_after_filter = len(candidates)

        if query.order_by is not None:
            column, descending = query.order_by
            candidates.sort(key=lambda row: row[column], reverse=descending)
        if query.limit is not None:
            candidates = candidates[: query.limit]

        if query.columns:
            candidates = [
                {column: row[column] for column in query.columns} for row in candidates
            ]

        return QueryResult(
            raw_plan=raw_plan,
            optimized_plan=self._optimized_plan(query, use_index),
            rows=candidates,
            stats={
                "rows_examined": rows_examined,
                "rows_after_filter": rows_after_filter,
                "rows_returned": len(candidates),
            },
        )

    def _raw_plan(self, query: Query) -> str:
        nodes = [f"SeqScan(table={self._table.name})"]
        if query.predicate is not None:
            nodes.append(f"Filter({query.predicate})")
        if query.order_by is not None:
            column, descending = query.order_by
            direction = "DESC" if descending else "ASC"
            nodes.append(f"Sort({column} {direction})")
        if query.limit is not None:
            nodes.append(f"Limit({query.limit})")
        if query.columns:
            nodes.append(f"Project({', '.join(query.columns)})")
        return " -> ".join(nodes)

    def _optimized_plan(self, query: Query, use_index: bool) -> str:
        if use_index:
            nodes = [f"IndexLookup(id={query.predicate.value!r})"]
        else:
            predicate = f", predicate={query.predicate}" if query.predicate else ""
            nodes = [f"SeqScan(table={self._table.name}{predicate})"]

        if query.order_by is not None and query.limit is not None:
            column, descending = query.order_by
            direction = "DESC" if descending else "ASC"
            nodes.append(f"TopN({column} {direction}, n={query.limit})")
        else:
            if query.order_by is not None:
                column, descending = query.order_by
                direction = "DESC" if descending else "ASC"
                nodes.append(f"Sort({column} {direction})")
            if query.limit is not None:
                nodes.append(f"Limit({query.limit})")

        if query.columns:
            nodes.append(f"Project({', '.join(query.columns)})")
        return " -> ".join(nodes)
