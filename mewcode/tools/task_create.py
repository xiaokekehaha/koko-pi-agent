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


class TaskCreateParams(BaseModel):
    title: str
    description: str = ""
    assignee: str = ""
    blocks: list[str] | None = None
    blocked_by: list[str] | None = None


class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = (
        "Create a shared task in the team's task board. "
        "Supports dependency tracking with blocks/blocked_by fields."
    )
    params_model = TaskCreateParams
    category = "command"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str, agent_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name
        self._agent_name = agent_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskCreateParams = params  # type: ignore[assignment]

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        task = store.create(
            title=p.title,
            description=p.description,
            assignee=p.assignee,
            blocks=p.blocks,
            blocked_by=p.blocked_by,
            created_by=self._agent_name,
        )

        return ToolResult(
            output=(
                f"Task created:\n"
                f"  ID: {task.id}\n"
                f"  Title: {task.title}\n"
                f"  Status: {task.status}\n"
                f"  Assignee: {task.assignee or '(unassigned)'}"
            )
        )
