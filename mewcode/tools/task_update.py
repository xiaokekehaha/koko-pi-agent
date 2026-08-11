# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.teams.manager import TeamManager


class TaskUpdateParams(BaseModel):
    task_id: str
    status: str | None = None
    assignee: str | None = None
    description: str | None = None
    add_blocks: list[str] | None = None
    add_blocked_by: list[str] | None = None


VALID_STATUSES = {"pending", "in_progress", "completed", "blocked"}


class TaskUpdateTool(Tool):
    name = "TaskUpdate"
    description = (
        "Update a shared task's status, assignee, description, or dependencies. "
        "Use add_blocks/add_blocked_by to add dependency relations."
    )
    params_model = TaskUpdateParams
    category = "command"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str) -> None:
        self._team_manager = team_manager
        self._team_name = team_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskUpdateParams = params  # type: ignore[assignment]

        if p.status and p.status not in VALID_STATUSES:
            return ToolResult(
                output=f"Invalid status '{p.status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
                is_error=True,
            )

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        task = store.update(
            task_id=p.task_id,
            status=p.status,
            assignee=p.assignee,
            description=p.description,
            add_blocks=p.add_blocks,
            add_blocked_by=p.add_blocked_by,
        )

        if task is None:
            return ToolResult(output=f"Task '{p.task_id}' not found", is_error=True)

        changes: list[str] = []
        if p.status:
            changes.append(f"status → {p.status}")
        if p.assignee is not None:
            changes.append(f"assignee → {p.assignee or '(unassigned)'}")
        if p.description is not None:
            changes.append("description updated")
        if p.add_blocks:
            changes.append(f"blocks += {', '.join(p.add_blocks)}")
        if p.add_blocked_by:
            changes.append(f"blocked_by += {', '.join(p.add_blocked_by)}")

        return ToolResult(
            output=f"Task {task.id} updated: {'; '.join(changes) if changes else 'no changes'}"
        )
