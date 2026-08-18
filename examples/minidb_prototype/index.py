"""PROTOTYPE: P2 B+ 树的插入、查找和叶子链范围扫描。

节点暂时放在 Python 内存对象中，没有编码进缓冲池页。这样可以先看清“叶子复制
分隔键、内部节点上推分隔键”这两个最容易混淆的动作。删除和并发 latch crabbing
属于下一阶段，不在这个一次运行的原型里伪装成已经完成。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass, field
from typing import TypeAlias


RowId: TypeAlias = tuple[int, int]


@dataclass
class BPlusNode:
    leaf: bool
    keys: list[int] = field(default_factory=list)
    values: list[RowId] = field(default_factory=list)
    children: list[BPlusNode] = field(default_factory=list)
    next_leaf: BPlusNode | None = None


class BPlusTree:
    """只支持唯一整数键的最小 B+ 树。"""

    def __init__(self, max_keys: int = 3) -> None:
        if max_keys < 3:
            raise ValueError("教学版 max_keys 至少为 3")
        self.max_keys = max_keys
        self.root = BPlusNode(leaf=True)

    def insert(self, key: int, value: RowId) -> None:
        split = self._insert(self.root, key, value)
        if split is None:
            return
        separator, right = split
        self.root = BPlusNode(
            leaf=False,
            keys=[separator],
            children=[self.root, right],
        )

    def _insert(
        self, node: BPlusNode, key: int, value: RowId
    ) -> tuple[int, BPlusNode] | None:
        if node.leaf:
            index = bisect_left(node.keys, key)
            if index < len(node.keys) and node.keys[index] == key:
                raise ValueError(f"B+ 树唯一键冲突：{key}")
            node.keys.insert(index, key)
            node.values.insert(index, value)
            if len(node.keys) <= self.max_keys:
                return None
            return self._split_leaf(node)

        child_index = bisect_right(node.keys, key)
        child_split = self._insert(node.children[child_index], key, value)
        if child_split is None:
            return None

        separator, right_child = child_split
        node.keys.insert(child_index, separator)
        node.children.insert(child_index + 1, right_child)
        if len(node.keys) <= self.max_keys:
            return None
        return self._split_internal(node)

    def _split_leaf(self, leaf: BPlusNode) -> tuple[int, BPlusNode]:
        split_at = (len(leaf.keys) + 1) // 2
        right = BPlusNode(
            leaf=True,
            keys=leaf.keys[split_at:],
            values=leaf.values[split_at:],
            next_leaf=leaf.next_leaf,
        )
        leaf.keys = leaf.keys[:split_at]
        leaf.values = leaf.values[:split_at]
        leaf.next_leaf = right

        # 叶子分裂：右叶第一个 key 仍保留在叶子，同时复制到父节点做路标。
        return right.keys[0], right

    def _split_internal(self, node: BPlusNode) -> tuple[int, BPlusNode]:
        middle = len(node.keys) // 2
        promoted = node.keys[middle]
        right = BPlusNode(
            leaf=False,
            keys=node.keys[middle + 1 :],
            children=node.children[middle + 1 :],
        )
        node.keys = node.keys[:middle]
        node.children = node.children[: middle + 1]

        # 内部节点分裂：中间 key 上推到父节点，不再留在左右子节点里。
        return promoted, right

    def search(self, key: int) -> RowId | None:
        leaf = self._find_leaf(key)
        index = bisect_left(leaf.keys, key)
        if index < len(leaf.keys) and leaf.keys[index] == key:
            return leaf.values[index]
        return None

    def range_scan(self, start: int, end: int) -> list[tuple[int, RowId]]:
        if start > end:
            return []
        leaf = self._find_leaf(start)
        result: list[tuple[int, RowId]] = []
        while leaf is not None:
            for key, value in zip(leaf.keys, leaf.values, strict=True):
                if key < start:
                    continue
                if key > end:
                    return result
                result.append((key, value))
            leaf = leaf.next_leaf
        return result

    def _find_leaf(self, key: int) -> BPlusNode:
        node = self.root
        while not node.leaf:
            node = node.children[bisect_right(node.keys, key)]
        return node

    def snapshot(self) -> dict[str, object]:
        """按层输出内部结构，并单独输出叶子链。"""

        levels: list[list[str]] = []
        queue: deque[tuple[BPlusNode, int]] = deque([(self.root, 0)])
        while queue:
            node, depth = queue.popleft()
            if len(levels) == depth:
                levels.append([])
            kind = "leaf" if node.leaf else "internal"
            levels[depth].append(f"{kind}{node.keys}")
            for child in node.children:
                queue.append((child, depth + 1))

        leaf = self.root
        while not leaf.leaf:
            leaf = leaf.children[0]
        leaf_chain: list[list[int]] = []
        while leaf is not None:
            leaf_chain.append(leaf.keys.copy())
            leaf = leaf.next_leaf

        return {"levels": levels, "leaf_chain": leaf_chain}
