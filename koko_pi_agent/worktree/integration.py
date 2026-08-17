# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from koko_pi_agent.worktree.manager import WorktreeManager


WORKTREE_NOTICE_TEMPLATE = """\
[WORKTREE CONTEXT]
You have inherited the parent agent's conversation context.
You are currently working in an isolated Git Worktree: {wt_path}
The parent agent's working directory is: {parent_cwd}

IMPORTANT:
- File paths mentioned in the parent conversation refer to the PARENT directory.
- You must translate them to your local worktree path before reading or editing.
- Always re-read files before editing — your copy may differ from the parent's version.
[/WORKTREE CONTEXT]
"""


def generate_worktree_name() -> str:
    """生成 worktree 名称，格式为 agent-a + 7 位十六进制。

    取 4 字节随机数 → 8 位十六进制，截取前 7 位，匹配 ^agent-a[0-9a-f]{7}$。
    """
    return f"agent-a{secrets.token_hex(4)[:7]}"


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    return WORKTREE_NOTICE_TEMPLATE.format(
        parent_cwd=parent_cwd,
        wt_path=wt_path,
    )

