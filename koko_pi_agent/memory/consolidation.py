# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""后台记忆整理（autoDream）。

满足时间门（≥24h）和会话门（≥5 sessions）后自动 fork 子 Agent，
扫描现有记忆，合并重复、删除过时、修正矛盾、维护索引。
空闲时自动整合碎片记忆，减少冗余，保持记忆库精简可靠。
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any

from koko_pi_agent.memory.auto_memory import ENTRYPOINT_NAME, MAX_ENTRYPOINT_LINES
from koko_pi_agent.memory.session import SessionManager

logger = logging.getLogger(__name__)

DEFAULT_MIN_HOURS = 24
DEFAULT_MIN_SESSIONS = 5
SCAN_THROTTLE_MS = 10 * 60 * 1000
LOCK_FILE = ".consolidate-lock"
HOLDER_STALE_MS = 60 * 60 * 1000


class MemoryConsolidator:
    """管理后台记忆整理的状态和执行。"""

    def __init__(
        self,
        work_dir: str,
        *,
        min_hours: int = DEFAULT_MIN_HOURS,
        min_sessions: int = DEFAULT_MIN_SESSIONS,
    ) -> None:
        self._work_dir = work_dir
        self._mem_dir = os.path.join(work_dir, ".koko", "memory")
        self._user_mem_dir = os.path.join(Path.home(), ".koko", "memory")
        self._min_hours = min_hours
        self._min_sessions = min_sessions
        self._last_scan_at = 0

    async def maybe_run(
        self,
        client: Any,
        conversation: Any,
        protocol: str,
    ) -> None:
        """检查门控条件，满足则后台执行一次整理。"""
        if not os.path.isdir(self._mem_dir):
            return

        # 时间门
        last_at = _read_last_consolidated_at(self._mem_dir)
        hours_since = (time.time() * 1000 - last_at) / 3_600_000
        if hours_since < self._min_hours:
            return

        # 扫描节流
        now = int(time.time() * 1000)
        if now - self._last_scan_at < SCAN_THROTTLE_MS:
            return
        self._last_scan_at = now

        # 会话门
        session_ids = _list_sessions_since(self._work_dir, last_at)
        if len(session_ids) < self._min_sessions:
            return

        # 获取锁
        prior_mtime = _try_acquire_lock(self._mem_dir)
        if prior_mtime is None:
            return

        logger.debug(
            "[consolidation] firing — %.1fh since last, %d sessions",
            hours_since,
            len(session_ids),
        )

        # 后台执行
        asyncio.ensure_future(
            self._run(client, conversation, protocol, session_ids, prior_mtime)
        )

    async def _run(
        self,
        client: Any,
        conversation: Any,
        protocol: str,
        session_ids: list[str],
        prior_mtime: int,
    ) -> None:
        try:
            await self._do_consolidation(
                client, conversation, protocol, session_ids
            )
        except Exception:
            logger.debug("[consolidation] failed, rolling back lock")
            _rollback_lock(self._mem_dir, prior_mtime)

    async def _do_consolidation(
        self,
        client: Any,
        conversation: Any,
        protocol: str,
        session_ids: list[str],
    ) -> None:
        from koko_pi_agent.agent import Agent
        from koko_pi_agent.conversation import ConversationManager
        from koko_pi_agent.permissions.checker import PermissionChecker
        from koko_pi_agent.tools import ToolRegistry
        from koko_pi_agent.tools.bash import BashTool
        from koko_pi_agent.tools.edit_file import EditFileTool
        from koko_pi_agent.tools.glob import GlobTool
        from koko_pi_agent.tools.grep import GrepTool
        from koko_pi_agent.tools.read_file import ReadFileTool
        from koko_pi_agent.tools.write_file import WriteFileTool

        transcript_dir = os.path.join(self._work_dir, ".koko", "sessions")
        prompt = _build_consolidation_prompt(
            self._mem_dir, self._user_mem_dir, transcript_dir, session_ids
        )

        # 构建子 Agent 的工具注册表
        registry = ToolRegistry()
        for tool_cls in [ReadFileTool, WriteFileTool, EditFileTool, GlobTool, GrepTool, BashTool]:
            registry.register(tool_cls())

        checker = PermissionChecker(self._work_dir, mode="bypass")

        conv = ConversationManager()
        conv.add_user_message(prompt)

        sub_agent = Agent(
            client=client,
            registry=registry,
            checker=checker,
            work_dir=self._work_dir,
            protocol=protocol,
            max_iterations=15,
        )

        async for _event in sub_agent.run(conv):
            pass  # drain

        logger.debug("[consolidation] completed")


# ---------------------------------------------------------------------------
# 锁文件管理
# ---------------------------------------------------------------------------


def _lock_path(mem_dir: str) -> str:
    return os.path.join(mem_dir, LOCK_FILE)


def _read_last_consolidated_at(mem_dir: str) -> int:
    """返回上次整理时间戳（ms）。锁文件不存在返回 0。"""
    path = _lock_path(mem_dir)
    try:
        return int(os.stat(path).st_mtime * 1000)
    except FileNotFoundError:
        return 0


def _try_acquire_lock(mem_dir: str) -> int | None:
    """获取锁。成功返回旧 mtime（ms），失败返回 None。"""
    path = _lock_path(mem_dir)
    mtime_ms: int | None = None
    holder_pid: int | None = None

    if os.path.exists(path):
        try:
            mtime_ms = int(os.stat(path).st_mtime * 1000)
            raw = Path(path).read_text().strip()
            holder_pid = int(raw) if raw else None
        except (ValueError, OSError):
            pass

    if mtime_ms is not None and time.time() * 1000 - mtime_ms < HOLDER_STALE_MS:
        if holder_pid is not None and _is_process_running(holder_pid):
            return None

    os.makedirs(mem_dir, exist_ok=True)
    Path(path).write_text(str(os.getpid()))

    # 回读验证
    try:
        verify = Path(path).read_text().strip()
        if int(verify) != os.getpid():
            return None
    except (ValueError, OSError):
        return None

    return mtime_ms if mtime_ms is not None else 0


def _rollback_lock(mem_dir: str, prior_mtime: int) -> None:
    path = _lock_path(mem_dir)
    try:
        if prior_mtime == 0:
            os.unlink(path)
            return
        Path(path).write_text("")
        t = prior_mtime / 1000
        os.utime(path, (t, t))
    except OSError:
        pass


def _is_process_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


def _list_sessions_since(work_dir: str, since_ms: int) -> list[str]:
    """返回 since_ms 之后被修改过的会话 ID。"""
    mgr = SessionManager(work_dir)
    since_ts = since_ms / 1000
    # last_active 是 datetime，转成秒级 epoch 再与阈值比较
    return [
        s.id
        for s in mgr.list()
        if s.last_active.timestamp() > since_ts
    ]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_consolidation_prompt(
    mem_dir: str,
    user_mem_dir: str,
    transcript_dir: str,
    session_ids: list[str],
) -> str:
    lines = [
        "# Dream: Memory Consolidation",
        "",
        "You are performing a dream — a reflective pass over your memory files. "
        "Synthesize what you've learned recently into durable, well-organized "
        "memories so that future sessions can orient quickly.",
        "",
        f"Project memory directory: `{mem_dir}`",
        f"User memory directory: `{user_mem_dir}`",
        "The memory directory already exists — write to it directly.",
        "",
        f"Session transcripts: `{transcript_dir}` (large JSONL files — grep narrowly, don't read whole files)",
        "",
        "---",
        "",
        "## Phase 1 — Orient",
        "",
        "- `ls` the memory directory to see what already exists",
        f"- Read `{ENTRYPOINT_NAME}` to understand the current index",
        "- Skim existing topic files so you improve them rather than creating duplicates",
        "",
        "## Phase 2 — Gather recent signal",
        "",
        "Look for new information worth persisting:",
        "",
        "1. **Existing memories that drifted** — facts that contradict something you see in the codebase now",
        "2. **Transcript search** — if you need specific context, grep the JSONL transcripts for narrow terms",
        "",
        "Don't exhaustively read transcripts. Look only for things you already suspect matter.",
        "",
        "## Phase 3 — Consolidate",
        "",
        "For each thing worth remembering, write or update a memory file. "
        "Each memory file uses YAML frontmatter with name, description, and metadata.type fields, "
        "followed by a Markdown body.",
        "",
        "Focus on:",
        "- Merging new signal into existing topic files rather than creating near-duplicates",
        '- Converting relative dates ("yesterday", "last week") to absolute dates',
        "- Deleting contradicted facts — if today's investigation disproves an old memory, fix it at the source",
        "",
        "## Phase 4 — Prune and index",
        "",
        f"Update `{ENTRYPOINT_NAME}` so it stays under {MAX_ENTRYPOINT_LINES} lines AND under ~25KB. "
        "It's an **index**, not a dump — each entry should be one line under ~150 characters: "
        "`- [Title](file.md) — one-line hook`. Never write memory content directly into it.",
        "",
        "- Remove pointers to memories that are now stale, wrong, or superseded",
        "- Demote verbose entries: if an index line is over ~200 chars, shorten the line, move the detail",
        "- Add pointers to newly important memories",
        "- Resolve contradictions — if two files disagree, fix the wrong one",
        "",
        "---",
        "",
        "**Tool constraints for this run:** Bash is restricted to read-only commands "
        "(`ls`, `find`, `grep`, `cat`, `stat`, `wc`, `head`, `tail`, and similar). "
        "Anything that writes, redirects to a file, or modifies state will be denied.",
        "",
    ]

    if session_ids:
        lines.append(f"Sessions since last consolidation ({len(session_ids)}):")
        for sid in session_ids:
            lines.append(f"- {sid}")

    lines.extend([
        "",
        "Return a brief summary of what you consolidated, updated, or pruned. "
        "If nothing changed (memories are already tight), say so.",
    ])

    return "\n".join(lines)
