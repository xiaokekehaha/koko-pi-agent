"""PROTOTYPE: P1 缓冲池、可扩展哈希与 LRU-K 的透明教学实现。

这里优先让状态可观察，而不是追求生产级性能。所有“磁盘页”都保存在内存字典中，
这样一次 demo 就能把重点放在 page_id、frame_id、pin_count 和脏页写回上。
"""

from __future__ import annotations

from collections import deque
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Bucket(Generic[K, V]):
    local_depth: int
    capacity: int
    entries: dict[K, V] = field(default_factory=dict)


class ExtendibleHashTable(Generic[K, V]):
    """只增长不收缩的可扩展哈希表。

    目录用哈希值的低 ``global_depth`` 位选桶。多个目录项可以指向同一个桶；
    桶满时只拆这个桶，必要时才把目录翻倍。
    """

    def __init__(self, bucket_capacity: int = 2) -> None:
        if bucket_capacity < 1:
            raise ValueError("bucket_capacity 必须大于 0")
        self._global_depth = 0
        self._bucket_capacity = bucket_capacity
        self._directory = [_Bucket[K, V](0, bucket_capacity)]
        self._lock = RLock()

    def _directory_index(self, key: K) -> int:
        mask = (1 << self._global_depth) - 1
        return hash(key) & mask

    def find(self, key: K) -> V | None:
        with self._lock:
            return self._directory[self._directory_index(key)].entries.get(key)

    def insert(self, key: K, value: V) -> None:
        with self._lock:
            while True:
                directory_index = self._directory_index(key)
                bucket = self._directory[directory_index]
                if key in bucket.entries or len(bucket.entries) < bucket.capacity:
                    bucket.entries[key] = value
                    return
                self._split_bucket(directory_index)

    def remove(self, key: K) -> bool:
        with self._lock:
            bucket = self._directory[self._directory_index(key)]
            return bucket.entries.pop(key, None) is not None

    def _split_bucket(self, directory_index: int) -> None:
        bucket = self._directory[directory_index]
        old_local_depth = bucket.local_depth

        if old_local_depth == self._global_depth:
            self._directory += self._directory.copy()
            self._global_depth += 1

        bucket.local_depth += 1
        sibling = _Bucket[K, V](bucket.local_depth, bucket.capacity)
        split_bit = 1 << old_local_depth

        for index, pointed_bucket in enumerate(self._directory):
            if pointed_bucket is bucket and index & split_bit:
                self._directory[index] = sibling

        old_entries = list(bucket.entries.items())
        bucket.entries.clear()
        for key, value in old_entries:
            destination = self._directory[self._directory_index(key)]
            destination.entries[key] = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            bucket_names: dict[int, str] = {}
            buckets: dict[str, dict[str, Any]] = {}
            directory: list[str] = []

            for bucket in self._directory:
                identity = id(bucket)
                if identity not in bucket_names:
                    name = f"B{len(bucket_names)}"
                    bucket_names[identity] = name
                    buckets[name] = {
                        "local_depth": bucket.local_depth,
                        "keys": sorted(bucket.entries),
                    }
                directory.append(bucket_names[identity])

            return {
                "global_depth": self._global_depth,
                "directory": directory,
                "buckets": buckets,
            }


class LRUKReplacer:
    """把不足 K 次和至少 K 次访问的 frame 分开管理。

    ``cold`` 中的 frame 反向 K 距离视为正无穷，优先淘汰；如果都在 ``hot``，
    则淘汰第 K 次最近访问最早的 frame。
    """

    def __init__(self, k: int = 2) -> None:
        if k < 1:
            raise ValueError("k 必须大于 0")
        self._k = k
        self._clock = 0
        self._history: dict[int, deque[int]] = {}
        self._cold: set[int] = set()
        self._hot: set[int] = set()
        self._evictable: set[int] = set()
        self._lock = RLock()

    def record_access(self, frame_id: int) -> None:
        with self._lock:
            self._clock += 1
            history = self._history.setdefault(frame_id, deque(maxlen=self._k))
            history.append(self._clock)
            if len(history) < self._k:
                self._cold.add(frame_id)
                self._hot.discard(frame_id)
            else:
                self._hot.add(frame_id)
                self._cold.discard(frame_id)

    def set_evictable(self, frame_id: int, evictable: bool) -> None:
        with self._lock:
            if evictable:
                self._evictable.add(frame_id)
            else:
                self._evictable.discard(frame_id)

    def evict(self) -> int | None:
        with self._lock:
            cold_candidates = self._cold & self._evictable
            if cold_candidates:
                victim = min(cold_candidates, key=lambda frame: self._history[frame][0])
            else:
                hot_candidates = self._hot & self._evictable
                if not hot_candidates:
                    return None
                victim = min(hot_candidates, key=lambda frame: self._history[frame][0])

            self._evictable.remove(victim)
            return victim

    def remove(self, frame_id: int) -> None:
        with self._lock:
            self._history.pop(frame_id, None)
            self._cold.discard(frame_id)
            self._hot.discard(frame_id)
            self._evictable.discard(frame_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cold": sorted(self._cold),
                "hot": sorted(self._hot),
                "evictable": sorted(self._evictable),
                "history": {
                    frame: list(history)
                    for frame, history in sorted(self._history.items())
                },
            }


class InMemoryDiskManager:
    """用深拷贝模拟磁盘读写，避免内存页和磁盘页偷偷共享对象。"""

    def __init__(self) -> None:
        self._pages: dict[int, dict[str, Any]] = {}
        self._next_page_id = 0
        self.read_count = 0
        self.write_count = 0
        self._lock = RLock()

    def allocate_page(self) -> int:
        with self._lock:
            page_id = self._next_page_id
            self._next_page_id += 1
            self._pages[page_id] = {}
            return page_id

    def read_page(self, page_id: int) -> dict[str, Any]:
        with self._lock:
            self.read_count += 1
            return deepcopy(self._pages[page_id])

    def write_page(self, page_id: int, data: dict[str, Any]) -> None:
        with self._lock:
            self.write_count += 1
            self._pages[page_id] = deepcopy(data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "page_ids": sorted(self._pages),
                "reads": self.read_count,
                "writes": self.write_count,
            }


@dataclass
class Frame:
    frame_id: int
    page_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    pin_count: int = 0
    is_dirty: bool = False


class PageGuard(AbstractContextManager[dict[str, Any]]):
    """把 fetch/unpin 配成一对，类似 Python 版 RAII。"""

    def __init__(
        self,
        buffer_pool: BufferPoolManager,
        page_id: int,
        data: dict[str, Any],
        write: bool,
    ) -> None:
        self._buffer_pool = buffer_pool
        self.page_id = page_id
        self._data = data
        self._write = write
        self._closed = False

    def __enter__(self) -> dict[str, Any]:
        return self._data

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._buffer_pool.unpin_page(self.page_id, dirty=self._write)
            self._closed = True


class BufferPoolManager:
    """固定 frame 数量的缓冲池。"""

    def __init__(self, disk: InMemoryDiskManager, pool_size: int = 3, k: int = 2) -> None:
        self._disk = disk
        self._frames = [Frame(frame_id=index) for index in range(pool_size)]
        self._free_frames = deque(range(pool_size))
        self._page_table: ExtendibleHashTable[int, int] = ExtendibleHashTable(
            bucket_capacity=2
        )
        self._replacer = LRUKReplacer(k)
        self._lock = RLock()

    def new_page(self, initial_data: dict[str, Any] | None = None) -> PageGuard:
        with self._lock:
            page_id = self._disk.allocate_page()
            frame = self._prepare_frame(page_id, initial_data or {})
            frame.is_dirty = True
            return PageGuard(self, page_id, frame.data, write=True)

    def fetch_page(self, page_id: int, *, write: bool = False) -> PageGuard:
        with self._lock:
            frame_id = self._page_table.find(page_id)
            if frame_id is None:
                frame = self._prepare_frame(page_id, self._disk.read_page(page_id))
            else:
                frame = self._frames[frame_id]
                frame.pin_count += 1
                self._replacer.record_access(frame.frame_id)
                self._replacer.set_evictable(frame.frame_id, False)
            return PageGuard(self, page_id, frame.data, write)

    def _prepare_frame(self, page_id: int, data: dict[str, Any]) -> Frame:
        if self._free_frames:
            frame_id = self._free_frames.popleft()
        else:
            victim = self._replacer.evict()
            if victim is None:
                raise RuntimeError("没有可淘汰 frame：检查 PageGuard 是否都已退出")
            frame_id = victim
            old_frame = self._frames[frame_id]
            if old_frame.page_id is not None:
                if old_frame.is_dirty:
                    self._disk.write_page(old_frame.page_id, old_frame.data)
                self._page_table.remove(old_frame.page_id)
            self._replacer.remove(frame_id)

        frame = self._frames[frame_id]
        frame.page_id = page_id
        frame.data = deepcopy(data)
        frame.pin_count = 1
        frame.is_dirty = False
        self._page_table.insert(page_id, frame_id)
        self._replacer.record_access(frame_id)
        self._replacer.set_evictable(frame_id, False)
        return frame

    def unpin_page(self, page_id: int, *, dirty: bool = False) -> None:
        with self._lock:
            frame_id = self._page_table.find(page_id)
            if frame_id is None:
                raise KeyError(f"page {page_id} 当前不在缓冲池")
            frame = self._frames[frame_id]
            if frame.pin_count == 0:
                raise RuntimeError(f"page {page_id} 被重复 unpin")
            frame.pin_count -= 1
            frame.is_dirty = frame.is_dirty or dirty
            if frame.pin_count == 0:
                self._replacer.set_evictable(frame_id, True)

    def flush_all(self) -> None:
        with self._lock:
            for frame in self._frames:
                if frame.page_id is not None and frame.is_dirty:
                    self._disk.write_page(frame.page_id, frame.data)
                    frame.is_dirty = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "frames": [
                    {
                        "frame_id": frame.frame_id,
                        "page_id": frame.page_id,
                        "pin_count": frame.pin_count,
                        "dirty": frame.is_dirty,
                    }
                    for frame in self._frames
                ],
                "page_table": self._page_table.snapshot(),
                "lru_k": self._replacer.snapshot(),
                "disk": self._disk.snapshot(),
            }
