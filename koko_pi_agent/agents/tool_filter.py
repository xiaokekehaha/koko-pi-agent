# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from koko_pi_agent.tools import ContributionOwner, ToolRegistry, ToolView

if TYPE_CHECKING:
    from koko_pi_agent.agents.parser import AgentDef
    from koko_pi_agent.teams.manager import TeamManager

ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

ASYNC_AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "ReadFile",
    "WebSearch",
    "TodoWrite",
    "Grep",
    "WebFetch",
    "Glob",
    "Bash",
    "EditFile",
    "WriteFile",
    "NotebookEdit",
    "Skill",
    "LoadSkill",
    "SyntheticOutput",
    "ToolSearch",
    "EnterWorktree",
    "ExitWorktree",
})

TEAMMATE_COORDINATION_TOOLS: frozenset[str] = frozenset({
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
})

# 队友在协作工具之外额外被挡掉的工具。组建和解散团队由 Lead 负责，队友只管干活
# 和相互协调，不参与团队成员管理。
TEAMMATE_DISALLOWED_TOOLS: frozenset[str] = frozenset({"TeamCreate", "TeamDelete"})

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: frozenset[str] = (
    ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS | frozenset({
        "CronCreate",
        "CronDelete",
        "CronList",
    })
)

# Coordinator 模式把 Lead 的工具集收窄到纯调度。
#
# 划线的标准不是「读」和「写」，而是这个工具会不会把大段内容灌进 Lead 的上下文。
# Lead 的上下文要装任务分解、队员状态和消息记录，一旦它能直接读文件、跑命令，
# 模型就会忍不住自己去查，几千行代码进来，真正该留给调度的空间就没了。
# 所以 ReadFile / Glob / Grep / Bash 都不在这里：需要看代码就派队员去看。
#
# 任务分派靠 Agent 的 prompt 写清楚，不靠共享任务表，因此 TaskCreate / TaskGet /
# TaskList / TaskUpdate 也不给 Lead，它们属于 TEAMMATE_COORDINATION_TOOLS，
# 是队员之间协调用的。Lead 掌握进度靠队员完成时回传的 <task-notification>。
#
# TeamDelete 必须留着：coordinator 模式由 TeamCreate 激活、TeamDelete 解除，
# 拿掉它 Lead 就再也退不出 coordinator 模式。
# TeamCreate 不需要在这里，激活之前工具集还没被收窄。
COORDINATOR_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "Agent",
    "SendMessage",
    "TaskStop",
    "SyntheticOutput",
    "TeamDelete",
})


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__")


def resolve_agent_tools(
    parent_registry: ToolRegistry,
    definition: AgentDef,
    is_background: bool = False,
) -> ToolRegistry:
    all_tools = {t.name: t for t in parent_registry.list_tools()}

    # 第 0 层：MCP 工具始终放行，先分离出来再做后续过滤
    mcp_tools = {name: tool for name, tool in all_tools.items() if _is_mcp_tool(name)}
    all_tools = {name: tool for name, tool in all_tools.items() if not _is_mcp_tool(name)}

    # 第 1 层：全局禁用工具
    for name in ALL_AGENT_DISALLOWED_TOOLS:
        all_tools.pop(name, None)

    # 第 2 层：自定义 agent 额外限制
    if definition.source in ("project", "user", "plugin"):
        for name in CUSTOM_AGENT_DISALLOWED_TOOLS:
            all_tools.pop(name, None)

    # 第 3 层：后台任务白名单
    if is_background:
        all_tools = {
            name: tool
            for name, tool in all_tools.items()
            if name in ASYNC_AGENT_ALLOWED_TOOLS
        }

    # 第 4 层：按 agent 定义中的禁用/允许列表过滤
    if definition.disallowed_tools:
        for name in definition.disallowed_tools:
            all_tools.pop(name, None)

    if definition.tools:
        allowed_set = set(definition.tools)
        all_tools = {
            name: tool
            for name, tool in all_tools.items()
            if name in allowed_set
        }

    return ToolView.borrow(
        parent_registry,
        names=(*mcp_tools, *all_tools),
    )


def build_teammate_tools(
    parent_registry: ToolRegistry,
    team_manager: TeamManager,
    team_name: str,
    agent_id: str,
    agent_name: str,
    backend_type: str,
    definition: AgentDef | None = None,
) -> ToolRegistry:
    from koko_pi_agent.teams.models import BackendType
    from koko_pi_agent.tools.send_message import SendMessageTool
    from koko_pi_agent.tools.task_create import TaskCreateTool
    from koko_pi_agent.tools.task_get import TaskGetTool
    from koko_pi_agent.tools.task_list import TaskListTool
    from koko_pi_agent.tools.task_update import TaskUpdateTool

    if backend_type == BackendType.IN_PROCESS.value:
        all_tools = {t.name: t for t in parent_registry.list_tools()}
        filtered = {
            name: tool
            for name, tool in all_tools.items()
            if name in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS
        }
    else:
        # 窗格队友整份继承，再挡掉两类：任何子 Agent 都不该有的，以及团队成员管理工具
        filtered = {
            name: tool
            for name, tool in ((t.name, t) for t in parent_registry.list_tools())
            if name not in ALL_AGENT_DISALLOWED_TOOLS
            and name not in TEAMMATE_DISALLOWED_TOOLS
        }

    # 协作工具必须绑定当前队友身份，不能借用 parent 中绑定 lead/其他队友的实例。
    filtered = {
        name: tool
        for name, tool in filtered.items()
        if name not in TEAMMATE_COORDINATION_TOOLS
    }

    # 应用 agent 定义中的工具限制
    if definition is not None:
        if definition.disallowed_tools:
            for name in definition.disallowed_tools:
                filtered.pop(name, None)
        if definition.tools:
            allowed_set = set(definition.tools) | TEAMMATE_COORDINATION_TOOLS
            filtered = {
                name: tool
                for name, tool in filtered.items()
                if name in allowed_set
            }

    coordination_tools = [
        TaskCreateTool(team_manager, team_name, agent_name),
        TaskGetTool(team_manager, team_name),
        TaskListTool(team_manager, team_name),
        TaskUpdateTool(team_manager, team_name),
        SendMessageTool(team_manager, team_name, agent_id, agent_name),
    ]

    return ToolView.borrow(
        parent_registry,
        names=(
            name
            for name in filtered
            if name not in TEAMMATE_COORDINATION_TOOLS
        ),
        additions=coordination_tools,
        local_owner=ContributionOwner(
            extension_id="koko_pi_agent.teammate-coordination",
            source="runtime-local",
        ),
    )


def clone_registry_for_fork(parent_registry: ToolRegistry) -> ToolRegistry:
    """Fork 专用：复制父注册表的全部工具，不做任何过滤。

    遇到 AgentTool 实例时浅复制并标记 query_source，
    确保 fork 子 Agent 不能再次 fork（运行时拦截），
    同时保持工具定义与父 Agent 字节一致以命中 prompt cache。
    """
    import copy

    from koko_pi_agent.tools.agent_tool import FORK_QUERY_SOURCE

    replacements: dict[str, Any] = {}
    for tool in parent_registry.list_tools():
        if tool.name == "Agent" and hasattr(tool, "query_source"):
            clone = copy.copy(tool)
            clone.query_source = FORK_QUERY_SOURCE
            replacements[tool.name] = clone
    return ToolView.borrow(parent_registry, replacements=replacements)


def apply_coordinator_filter(registry: ToolRegistry) -> ToolRegistry:
    # MCP 工具同样不放行：抓网页、查数据库这类返回值动辄几千 token，
    # 灌进 Lead 的上下文和让它自己读文件是一个性质，要用就派队员去用。
    names = (
        tool.name
        for tool in registry.list_tools()
        if tool.name in COORDINATOR_MODE_ALLOWED_TOOLS
    )
    return ToolView.borrow(registry, names=names)
