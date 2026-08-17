# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

import json
import logging
from pathlib import Path

from koko_pi_agent.worktree.models import WorktreeSession

log = logging.getLogger(__name__)

SESSION_FILENAME = "worktree_session.json"


def _session_path(mewcode_dir: Path) -> Path:
    return mewcode_dir / SESSION_FILENAME


def save_worktree_session(
    mewcode_dir: Path,
    session: WorktreeSession | None,
) -> None:
    path = _session_path(mewcode_dir)
    if session is None:
        # 传入 nil 时直接删除文件而非写空 JSON，
        # 避免遗留无意义的空文件。文件不存在时静默忽略。
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "original_cwd": session.original_cwd,
        "worktree_path": session.worktree_path,
        "worktree_name": session.worktree_name,
        "original_branch": session.original_branch,
        "original_head_commit": session.original_head_commit,
        "session_id": session.session_id,
        "hook_based": session.hook_based,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_worktree_session(mewcode_dir: Path) -> WorktreeSession | None:
    path = _session_path(mewcode_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data or "worktree_path" not in data:
            return None
        return WorktreeSession(
            original_cwd=data["original_cwd"],
            worktree_path=data["worktree_path"],
            worktree_name=data["worktree_name"],
            original_branch=data["original_branch"],
            original_head_commit=data["original_head_commit"],
            session_id=data.get("session_id", ""),
            hook_based=data.get("hook_based", False),
        )
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to load worktree session: %s", e)
        return None

