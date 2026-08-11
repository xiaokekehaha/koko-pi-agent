# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from pathlib import Path


class FileStateCache:
    """Tracks which files have been read, enforcing read-before-edit.

    Stores { absolute_path: mtime_ns } after each ReadFile call.
    EditFile and WriteFile check the cache before proceeding:
      - Gate 1: file must have been read (present in cache).
      - Gate 2: file must not have been modified since the read (mtime_ns matches).
    """

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def record(self, path: str, mtime_ns: int) -> None:
        """Record a file's mtime after a successful read."""
        self._cache[path] = mtime_ns

    def check(self, path: str) -> tuple[bool, str]:
        """Check whether the file is safe to edit/write.

        Returns (ok, error_message). If ok is True, error_message is empty.
        """
        cached_mtime_ns = self._cache.get(path)
        if cached_mtime_ns is None:
            return False, "Error: file has not been read yet. Read it first before editing."

        try:
            current_mtime_ns = Path(path).stat().st_mtime_ns
        except OSError:
            return True, ""

        if current_mtime_ns != cached_mtime_ns:
            return False, "Error: file has been modified since last read. Read it again before editing."

        return True, ""

    def update(self, path: str) -> None:
        """Update the cache entry after a successful edit/write."""
        try:
            mtime_ns = Path(path).stat().st_mtime_ns
            self._cache[path] = mtime_ns
        except OSError:
            self._cache.pop(path, None)
