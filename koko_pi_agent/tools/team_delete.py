# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from koko_pi_agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from koko_pi_agent.agent import Agent
    from koko_pi_agent.teams.manager import TeamManager


class TeamDeleteParams(BaseModel):
    team_name: str


class TeamDeleteTool(Tool):
    name = "TeamDelete"
    description = (
        "Delete an Agent Team. Terminates all pane processes, removes worktrees, "
        "cleans up mailbox and team directory. Requires all members to be idle."
    )
    params_model = TeamDeleteParams
    category = "command"
    is_concurrency_safe = False


    def __init__(self, team_manager: TeamManager, parent_agent: Agent | None = None) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamDeleteParams = params  # type: ignore[assignment]

        from koko_pi_agent.teams.manager import TeamError

        try:
            self._team_manager.delete_team(p.team_name)
        except TeamError as e:
            return ToolResult(output=str(e), is_error=True)
        except Exception as e:
            return ToolResult(output=f"Failed to delete team: {e}", is_error=True)

        # coordinator 模式由配置在启动时决定，拆团队不改变它，这里不碰工具集
        return ToolResult(output=f"Team '{p.team_name}' deleted successfully.")
