# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from koko_pi_agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from koko_pi_agent.agent import Agent
    from koko_pi_agent.teams.manager import TeamManager


class TeamCreateParams(BaseModel):
    team_name: str
    description: str = ""


class TeamCreateTool(Tool):
    name = "TeamCreate"
    description = (
        "Create a new team for coordinating multiple agents.\n\n"
        "## When to Use\n\n"
        "Use this tool proactively whenever:\n"
        "- The user explicitly asks to use a team, swarm, or group of agents\n"
        "- The user mentions wanting agents to work together, coordinate, or collaborate\n"
        "- A task requires sequential or parallel collaboration between multiple agents\n\n"
        "When in doubt about whether a task warrants a team, prefer spawning a team.\n\n"
        "## Team Workflow\n\n"
        "1. **Create a team** with TeamCreate\n"
        "2. **Spawn teammates** using the Agent tool with team_name and name parameters "
        "— this is REQUIRED to create long-running team members\n"
        "3. Teammates work independently and communicate via **SendMessage**\n"
        "4. When a teammate finishes, it sends its result to \"lead\" via SendMessage, then goes idle\n"
        "5. The lead collects and synthesizes all teammate results\n\n"
        "## CRITICAL: Spawning Teammates\n\n"
        "To add a member to a team, you MUST pass both team_name and name to the Agent tool:\n"
        "```\nAgent({\n"
        '  "team_name": "<team name from step 1>",\n'
        '  "name": "<member name, e.g. reviewer>",\n'
        '  "prompt": "...",\n'
        '  "description": "..."\n'
        "})\n```\n"
        "Without team_name, the agent runs as a one-shot sub-agent that blocks and returns inline "
        "— it will NOT be a team member.\n\n"
        "## Teammate Idle State\n\n"
        "Teammates go idle after every turn — this is completely normal. "
        "Sending a message to an idle teammate wakes them up.\n\n"
        "## Communication\n\n"
        "- Use SendMessage to talk to teammates by name\n"
        "- Messages from teammates arrive as system reminders at the start of each turn\n"
        "- Messages are delivered automatically — you do NOT need to manually check your inbox"
    )
    params_model = TeamCreateParams
    category = "command"
    is_concurrency_safe = False


    def __init__(
        self,
        team_manager: TeamManager,
        parent_agent: Agent,
        teammate_mode: str = "",
        is_interactive: bool = True,
        enable_coordinator_mode: bool = False,
    ) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent
        self._teammate_mode = teammate_mode
        self._is_interactive = is_interactive
        self._enable_coordinator_mode = enable_coordinator_mode


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamCreateParams = params  # type: ignore[assignment]

        from koko_pi_agent.teams.backend_detect import BackendDetectionError

        try:
            backend = self._team_manager.detect_backend(
                self._teammate_mode, self._is_interactive
            )
        except BackendDetectionError as e:
            return ToolResult(output=str(e), is_error=True)

        try:
            team = self._team_manager.create_team(
                name=p.team_name,
                lead_agent_id=self._parent_agent.agent_id,
                description=p.description,
                teammate_mode=self._teammate_mode,
                is_interactive=self._is_interactive,
            )
        except Exception as e:
            return ToolResult(output=f"Failed to create team: {e}", is_error=True)

        # coordinator 模式由配置在启动时决定，建团队不改变它，这里不碰工具集
        return ToolResult(
            output=(
                f"Team '{team.name}' created successfully.\n"
                f"Backend: {backend.value}\n"
                f"Config: {team.config_path}\n"
                f"Use Agent tool with team_name='{team.name}' to spawn teammates."
            )
        )
