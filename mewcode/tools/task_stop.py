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


class TaskStopParams(BaseModel):
    teammate: str


class TaskStopTool(Tool):
    """中止一个在跑的队员。

    Coordinator 派错方向时用它及时止损，不用等队员把错的活干完。

    接的是 TeamManager 而不是后台任务表：队员按后端分两条路生出来，
    in-process 的进任务表，tmux / iTerm2 的是独立进程，只认任务表会漏掉后者。
    """

    name = "TaskStop"
    description = (
        "Stop a running teammate. Pass the teammate name as it appears in the from= field "
        "of a team-notification. Use this when you sent a teammate in the wrong direction, "
        "for example when the user changes requirements after you launched it."
    )
    params_model = TaskStopParams
    category = "command"
    is_concurrency_safe = False


    def __init__(self, team_manager: TeamManager) -> None:
        self._team_manager = team_manager


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskStopParams = params  # type: ignore[assignment]

        if not p.teammate:
            return ToolResult(output="Error: teammate is required", is_error=True)

        result = self._team_manager.stop_member(p.teammate)
        if result is None:
            known = self._known_members()
            return ToolResult(
                output=f"Error: teammate '{p.teammate}' not found. Known teammates: {known}",
                is_error=True,
            )

        team_name, stopped = result
        # 已经停下的队员再停一次不算错，把当前状态回给模型，免得它反复重试
        if not stopped:
            return ToolResult(
                output=f"Teammate '{p.teammate}' in team '{team_name}' is not running, nothing to stop"
            )

        return ToolResult(output=f"Teammate '{p.teammate}' in team '{team_name}' stopped.")


    def _known_members(self) -> str:
        """把当前所有队员名列给模型，省得它照着记错的名字反复重试。"""
        names: list[str] = []
        for team_name in self._team_manager.list_teams():
            team = self._team_manager.get_team(team_name)
            if team is not None:
                names.extend(m.name for m in team.members)
        return ", ".join(names) if names else "(none)"
