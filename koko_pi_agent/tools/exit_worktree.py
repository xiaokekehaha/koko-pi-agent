# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from koko_pi_agent.tools.base import Tool, ToolResult
from koko_pi_agent.worktree.changes import count_worktree_changes

if TYPE_CHECKING:
    from koko_pi_agent.worktree.manager import WorktreeManager


class ExitWorktreeParams(BaseModel):
    action: str = Field(
        description='"keep" leaves the worktree and branch on disk; "remove" deletes both.',
    )
    discard_changes: Optional[bool] = Field(
        default=None,
        description=(
            'Required true when action is "remove" and the worktree has '
            "uncommitted files or unmerged commits. "
            "The tool will refuse and list them otherwise."
        ),
    )


class ExitWorktreeTool(Tool):
    name = "ExitWorktree"
    description = (
        "Exits a worktree session created by EnterWorktree and restores "
        "the original working directory"
    )
    params_model = ExitWorktreeParams
    category = "command"


    def __init__(self, worktree_manager: WorktreeManager) -> None:
        self._manager = worktree_manager


    async def execute(self, params: ExitWorktreeParams) -> ToolResult:
        session = self._manager.get_current_session()
        if session is None:
            return ToolResult(
                output=(
                    "No-op: there is no active EnterWorktree session to exit. "
                    "This tool only operates on worktrees created by EnterWorktree "
                    "in the current session — it will not touch worktrees created "
                    "manually or in a previous session. No filesystem changes were made."
                ),
                is_error=True,
            )

        action = params.action
        if action not in ("keep", "remove"):
            return ToolResult(
                output=f'Invalid action "{action}". Must be "keep" or "remove".',
                is_error=True,
            )

        discard = params.discard_changes or False

        if action == "remove" and not discard:
            changes = count_worktree_changes(
                session.worktree_path, session.original_head_commit
            )
            if changes.uncommitted > 0 or changes.new_commits > 0:
                parts = []
                if changes.uncommitted > 0:
                    word = "file" if changes.uncommitted == 1 else "files"
                    parts.append(f"{changes.uncommitted} uncommitted {word}")
                if changes.new_commits > 0:
                    word = "commit" if changes.new_commits == 1 else "commits"
                    parts.append(f"{changes.new_commits} {word}")
                return ToolResult(
                    output=(
                        f"Worktree has {' and '.join(parts)}. "
                        "Removing will discard this work permanently. "
                        "Confirm with the user, then re-invoke with "
                        'discard_changes: true — or use action: "keep" '
                        "to preserve the worktree."
                    ),
                    is_error=True,
                )

        worktree_path = session.worktree_path
        original_cwd = session.original_cwd
        wt_name = session.worktree_name

        try:
            await self._manager.exit(wt_name, action=action, discard_changes=discard)
        except Exception as e:
            return ToolResult(
                output=f"Error exiting worktree: {e}", is_error=True
            )

        if action == "keep":
            return ToolResult(
                output=(
                    f"Exited worktree. Your work is preserved at {worktree_path}. "
                    f"Session is now back in {original_cwd}."
                )
            )

        return ToolResult(
            output=(
                f"Exited and removed worktree at {worktree_path}. "
                f"Session is now back in {original_cwd}."
            )
        )
