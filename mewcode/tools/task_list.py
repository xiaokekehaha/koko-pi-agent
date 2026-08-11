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


class TaskListParams(BaseModel):
    status: str | None = None
    assignee: str | None = None


class TaskListTool(Tool):
    name = "TaskList"
    description = (
        "List all shared tasks in the team's task board. "
        "Optionally filter by status (pending/in_progress/completed/blocked) or assignee."
    )
    params_model = TaskListParams
    category = "read"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str) -> None:
        self._team_manager = team_manager
        self._team_name = team_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskListParams = params  # type: ignore[assignment]

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        tasks = store.list_tasks(status=p.status, assignee=p.assignee)

        if not tasks:
            filters = []
            if p.status:
                filters.append(f"status={p.status}")
            if p.assignee:
                filters.append(f"assignee={p.assignee}")
            filter_str = f" (filters: {', '.join(filters)})" if filters else ""
            return ToolResult(output=f"No tasks found{filter_str}")

        status_icons = {
            "pending": "○",
            "in_progress": "◐",
            "completed": "●",
            "blocked": "✕",
        }

        lines = [f"Tasks ({len(tasks)}):"]
        for t in tasks:
            icon = status_icons.get(t.status, "?")
            assignee = f" [{t.assignee}]" if t.assignee else ""
            deps = ""
            if t.blocked_by:
                deps = f" (blocked by: {', '.join(t.blocked_by)})"
            lines.append(f"  {icon} [{t.id}] {t.title}{assignee}{deps}")

        return ToolResult(output="\n".join(lines))
