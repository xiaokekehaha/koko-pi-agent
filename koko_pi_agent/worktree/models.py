# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Worktree:
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime = field(default_factory=datetime.now)


@dataclass
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str = ""
    hook_based: bool = False

