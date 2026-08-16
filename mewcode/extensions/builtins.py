from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from mewcode.extensions.contracts import ExtensionDefinition, ToolProfile
from mewcode.extensions.host import ExtensionAPI, ExtensionCatalog, ExtensionHost
from mewcode.tools import ToolRegistry

if TYPE_CHECKING:
    from mewcode.agents.loader import AgentLoader
    from mewcode.agents.task_manager import TaskManager
    from mewcode.agents.trace import TraceManager
    from mewcode.skills.executor import SkillExecutor
    from mewcode.skills.loader import SkillLoader
    from mewcode.teams.manager import TeamManager
    from mewcode.worktree import WorktreeManager


class BuiltinAgent(Protocol):
    registry: ToolRegistry
    agent_id: str

    @property
    def plan_mode(self) -> bool: ...

    def _get_plan_path(self) -> Any: ...


@dataclass(frozen=True)
class BuiltinRuntimeBindings:
    agent: BuiltinAgent
    registry: ToolRegistry
    protocol: str
    file_history: Any = None
    agent_loader: AgentLoader | None = None
    task_manager: TaskManager | None = None
    trace_manager: TraceManager | None = None
    provider_config: Any = None
    worktree_manager: WorktreeManager | None = None
    team_manager: TeamManager | None = None
    skill_loader: SkillLoader | None = None
    skill_executor: SkillExecutor | None = None
    on_skill_installed: Callable[[str], None] | None = None
    bash_sandbox: Any = None
    bash_sandbox_config: Any = None
    enable_fork: bool = False
    teammate_mode: str = "in-process"
    is_interactive: bool = False
    enable_coordinator_mode: bool = False
    team_name: str = ""
    agent_name: str = ""
    from_agent_id: str = ""
    synthetic_output_schema: dict[str, Any] | None = None


class BuiltinBindingError(ValueError):
    pass


T = TypeVar("T")


def _required(value: T | None, field_name: str, tool_name: str) -> T:
    if value is None:
        raise BuiltinBindingError(
            f"Tool '{tool_name}' requires BuiltinRuntimeBindings.{field_name}"
        )
    return value


_PROFILE_TOOL_NAMES: dict[ToolProfile, tuple[str, ...]] = {
    ToolProfile.TUI_LEAD: (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Bash",
        "Glob",
        "Grep",
        "LoadSkill",
        "InstallSkill",
        "ToolSearch",
        "AskUserQuestion",
        "ExitPlanMode",
        "EnterWorktree",
        "ExitWorktree",
        "Agent",
        "TeamCreate",
        "TeamDelete",
        "SyntheticOutput",
        "TaskStop",
    ),
    ToolProfile.PROMPT_LEAD: (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Bash",
        "Glob",
        "Grep",
        "ToolSearch",
        "Agent",
        "TeamCreate",
        "TeamDelete",
        "SyntheticOutput",
        "TaskStop",
    ),
    ToolProfile.REMOTE_LEAD: (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Bash",
        "Glob",
        "Grep",
        "ToolSearch",
        "LoadSkill",
        "Agent",
        "TeamCreate",
        "TeamDelete",
        "TaskStop",
        "SyntheticOutput",
    ),
    ToolProfile.TEAMMATE_WORKER: (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Bash",
        "Glob",
        "Grep",
        "ToolSearch",
        "SyntheticOutput",
        "EnterWorktree",
        "ExitWorktree",
        "LoadSkill",
        "InstallSkill",
        "SendMessage",
        "TaskCreate",
        "TaskGet",
        "TaskList",
        "TaskUpdate",
    ),
}


def tool_names_for_profile(profile: ToolProfile) -> tuple[str, ...]:
    return _PROFILE_TOOL_NAMES[profile]


def _create_builtin_tool(
    name: str,
    bindings: BuiltinRuntimeBindings,
    file_state_cache: Any,
) -> Any:
    if name == "ReadFile":
        from mewcode.tools.read_file import ReadFile

        return ReadFile(file_state_cache=file_state_cache)
    if name == "WriteFile":
        from mewcode.tools.write_file import WriteFile

        return WriteFile(
            file_history=bindings.file_history,
            file_state_cache=file_state_cache,
        )
    if name == "EditFile":
        from mewcode.tools.edit_file import EditFile

        return EditFile(
            file_history=bindings.file_history,
            file_state_cache=file_state_cache,
        )
    if name == "Bash":
        from mewcode.tools.bash import Bash

        tool = Bash()
        if bindings.bash_sandbox is not None:
            tool.sandbox = bindings.bash_sandbox
            tool.sandbox_config = bindings.bash_sandbox_config
        return tool
    if name == "Glob":
        from mewcode.tools.glob import Glob

        return Glob()
    if name == "Grep":
        from mewcode.tools.grep import Grep

        return Grep()
    if name == "LoadSkill":
        from mewcode.tools.load_skill import LoadSkill

        tool = LoadSkill()
        tool.set_agent(bindings.agent)
        tool.set_loader(_required(bindings.skill_loader, "skill_loader", name))
        if bindings.skill_executor is not None:
            tool.set_executor(bindings.skill_executor)
        return tool
    if name == "InstallSkill":
        from mewcode.tools.install_skill import InstallSkillTool

        tool = InstallSkillTool()
        tool.set_loader(_required(bindings.skill_loader, "skill_loader", name))
        if bindings.on_skill_installed is not None:
            tool.set_on_installed(bindings.on_skill_installed)
        return tool
    if name == "ToolSearch":
        from mewcode.tools.impl.tool_search import ToolSearchTool

        return ToolSearchTool(bindings.registry, protocol=bindings.protocol)
    if name == "AskUserQuestion":
        from mewcode.tools.ask_user import AskUserTool

        return AskUserTool()
    if name == "ExitPlanMode":
        from mewcode.tools.exit_plan_mode import ExitPlanModeTool

        return ExitPlanModeTool(
            is_plan_mode=lambda: bindings.agent.plan_mode,
            plan_exists=lambda: bindings.agent._get_plan_path().exists(),
        )
    if name == "EnterWorktree":
        from mewcode.tools.enter_worktree import EnterWorktreeTool

        return EnterWorktreeTool(
            worktree_manager=_required(
                bindings.worktree_manager, "worktree_manager", name
            )
        )
    if name == "ExitWorktree":
        from mewcode.tools.exit_worktree import ExitWorktreeTool

        return ExitWorktreeTool(
            worktree_manager=_required(
                bindings.worktree_manager, "worktree_manager", name
            )
        )
    if name == "Agent":
        from mewcode.tools.agent_tool import AgentTool

        return AgentTool(
            agent_loader=_required(bindings.agent_loader, "agent_loader", name),
            task_manager=_required(bindings.task_manager, "task_manager", name),
            trace_manager=_required(bindings.trace_manager, "trace_manager", name),
            parent_agent=bindings.agent,
            enable_fork=bindings.enable_fork,
            provider_config=bindings.provider_config,
            worktree_manager=bindings.worktree_manager,
            team_manager=bindings.team_manager,
        )
    if name == "TeamCreate":
        from mewcode.tools.team_create import TeamCreateTool

        return TeamCreateTool(
            team_manager=_required(bindings.team_manager, "team_manager", name),
            parent_agent=bindings.agent,
            teammate_mode=bindings.teammate_mode,
            is_interactive=bindings.is_interactive,
            enable_coordinator_mode=bindings.enable_coordinator_mode,
        )
    if name == "TeamDelete":
        from mewcode.tools.team_delete import TeamDeleteTool

        return TeamDeleteTool(
            team_manager=_required(bindings.team_manager, "team_manager", name),
            parent_agent=bindings.agent,
        )
    if name == "SyntheticOutput":
        from mewcode.tools.synthetic_output import SyntheticOutputTool

        return SyntheticOutputTool(json_schema=bindings.synthetic_output_schema)
    if name == "TaskStop":
        from mewcode.tools.task_stop import TaskStopTool

        return TaskStopTool(
            team_manager=_required(bindings.team_manager, "team_manager", name)
        )
    if name == "SendMessage":
        from mewcode.tools.send_message import SendMessageTool

        return SendMessageTool(
            team_manager=_required(bindings.team_manager, "team_manager", name),
            team_name=bindings.team_name,
            from_agent_id=bindings.from_agent_id or bindings.agent_name,
            from_agent_name=bindings.agent_name,
        )
    if name == "TaskCreate":
        from mewcode.tools.task_create import TaskCreateTool

        return TaskCreateTool(
            _required(bindings.team_manager, "team_manager", name),
            bindings.team_name,
            bindings.agent_name,
        )
    if name == "TaskGet":
        from mewcode.tools.task_get import TaskGetTool

        return TaskGetTool(
            _required(bindings.team_manager, "team_manager", name),
            bindings.team_name,
        )
    if name == "TaskList":
        from mewcode.tools.task_list import TaskListTool

        return TaskListTool(
            _required(bindings.team_manager, "team_manager", name),
            bindings.team_name,
        )
    if name == "TaskUpdate":
        from mewcode.tools.task_update import TaskUpdateTool

        return TaskUpdateTool(
            _required(bindings.team_manager, "team_manager", name),
            bindings.team_name,
        )
    raise AssertionError(f"Unknown builtin tool '{name}'")


def _install_builtin_tools(api: ExtensionAPI, raw_bindings: Any) -> None:
    from mewcode.tools.file_state_cache import FileStateCache

    if not isinstance(raw_bindings, BuiltinRuntimeBindings):
        raise BuiltinBindingError(
            "mewcode.builtin-tools requires BuiltinRuntimeBindings"
        )
    if raw_bindings.agent.registry is not raw_bindings.registry:
        raise BuiltinBindingError(
            "Agent and bindings must share the runtime ToolRegistry"
        )

    file_state_cache = FileStateCache()
    for name in tool_names_for_profile(api.context.profile):
        api.register_tool(_create_builtin_tool(name, raw_bindings, file_state_cache))


def create_builtin_extension_host() -> ExtensionHost:
    return ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="mewcode.builtin-tools",
                    display_name="MewCode built-in tools",
                    source="builtin",
                    installer=_install_builtin_tools,
                )
            ]
        )
    )
