# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.agents.loader import AgentLoader
    from mewcode.agents.task_manager import TaskManager
    from mewcode.agents.trace import TraceManager
    from mewcode.client import LLMClient

log = logging.getLogger(__name__)


class AgentToolParams(BaseModel):
    prompt: str
    description: str
    subagent_type: str | None = None
    model: str | None = None
    run_in_background: bool = False
    name: str | None = None
    isolation: str | None = None
    plan_mode_required: bool = Field(
        default=False,
        description=(
            "Only meaningful together with team_name. When true, the teammate starts in "
            "plan mode: it can read and investigate but cannot modify anything until it "
            "submits a plan and you approve it via SendMessage with "
            "message_type='plan_approval_response'. Use it for risky or ambiguous tasks "
            "where a wrong direction would cost a lot of rework."
        ),
    )
    team_name: str | None = Field(
        default=None,
        description=(
            "REQUIRED when creating team members. Spawns the agent as a long-running "
            "teammate under this team (created via TeamCreate). Unlike regular sub-agents, "
            "team members run in their own terminal, persist after the lead returns, and "
            "communicate with each other via SendMessage. Without team_name the agent "
            "runs as a one-shot sub-agent that blocks and returns inline."
        ),
    )


PERMISSION_MODE_MAP = {
    "default": "DEFAULT",
    "acceptEdits": "ACCEPT_EDITS",
    "bypassPermissions": "BYPASS",
}


FORK_QUERY_SOURCE = "agent:builtin:fork"

# 省略 subagent_type 且 fork 被关掉时，回退到这个通用 agent
GENERAL_PURPOSE_AGENT_TYPE = "general-purpose"

TEAMMATE_ADDENDUM = (
    "\n\nIMPORTANT: You are running as an agent in a team.\n"
    "Just writing a response in text is not visible to others\n"
    "on your team - you MUST use the SendMessage tool.\n"
    "The user interacts primarily with the team lead.\n"
    "Your work is coordinated through the task system\n"
    "and teammate messaging.\n\n"
    "You are working in an isolated Git worktree. "
    "All file paths you use MUST be relative to your current working directory. "
    "Do NOT use absolute paths from the original project — they are outside your sandbox and will be rejected."
)


class AgentTool(Tool):
    name = "Agent"
    description = (
        "Launch a sub-agent to handle a task in an isolated context. "
        "Use subagent_type to select a predefined agent type (e.g. Explore, Plan, general-purpose), "
        "or leave it empty to fork the current conversation. "
        "Use team_name to spawn a teammate in an existing team."
    )
    params_model = AgentToolParams
    category = "command"
    is_concurrency_safe = False


    def __init__(
        self,
        agent_loader: AgentLoader,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        parent_agent: Agent,
        enable_fork: bool = False,
        provider_config: Any = None,
        worktree_manager: Any = None,
        team_manager: Any = None,
    ) -> None:
        self._agent_loader = agent_loader
        self._task_manager = task_manager
        self._trace_manager = trace_manager
        self._parent_agent = parent_agent
        self._enable_fork = enable_fork
        self._provider_config = provider_config
        self._worktree_manager = worktree_manager
        self._team_manager = team_manager
        self.query_source: str = ""

    async def execute(self, params: BaseModel) -> ToolResult:
        p: AgentToolParams = params  # type: ignore[assignment]

        if p.team_name:
            return await self._execute_as_teammate(p)

        isolation = ""
        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn and defn.isolation:
                isolation = defn.isolation

        if isolation == "worktree":
            return await self._execute_with_worktree(p)

        from mewcode.agents.fork import ForkError, build_forked_messages
        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import clone_registry_for_fork, resolve_agent_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )

        definition: AgentDef | None = None
        conversation: ConversationManager

        # 省略 subagent_type 时的走向由 enable_fork 决定：开着走 fork（继承父对话），
        # 关着就当成没指定类型，回退到通用 agent。这里不报错，因为模型只是没填一个
        # 可选参数，为此中断一次调用不值得，回退到通用 agent 一样能把活干了。
        effective_type = p.subagent_type
        if not effective_type and not self._enable_fork:
            effective_type = GENERAL_PURPOSE_AGENT_TYPE

        if effective_type:
            definition = self._agent_loader.get(effective_type)
            if definition is None:
                return ToolResult(
                    output=f"Unknown agent type: '{effective_type}'. "
                    f"Available types: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
            conversation = ConversationManager()
        else:
            # fork 子 Agent 不允许再次 fork，防止无限嵌套
            if self.query_source == FORK_QUERY_SOURCE:
                return ToolResult(
                    output="Error: cannot fork from a forked agent. "
                    "Use subagent_type to spawn a definition-based agent instead.",
                    is_error=True,
                )
            try:
                parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                if parent_conv is None:
                    return ToolResult(
                        output="Cannot fork: no active conversation in parent agent.",
                        is_error=True,
                    )
                conversation = build_forked_messages(parent_conv, p.prompt)
            except ForkError as e:
                return ToolResult(output=str(e), is_error=True)

            definition = AgentDef(
                agent_type="fork",
                when_to_use="Forked from parent agent",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",
                max_turns=self._parent_agent.max_iterations,
                permission_mode="bypassPermissions",
                source="builtin",
            )

        # 选择 LLM 客户端
        client = self._select_llm(p, definition)

        # 判断是否后台运行
        is_fork = not effective_type
        is_background = p.run_in_background or definition.background
        if is_fork:
            is_background = True

        # 构建子 agent 工具注册表
        _base_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        if is_fork:
            # fork 继承父 Agent 的完整工具池，确保子 Agent 拥有相同的工具能力，
            # AgentTool 实例的 query_source 被标记为 fork 以拦截嵌套
            filtered_registry = clone_registry_for_fork(_base_registry)
        else:
            filtered_registry = resolve_agent_tools(
                _base_registry, definition, is_background
            )

        # 为子 agent 创建权限检查器
        pm_str = definition.permission_mode
        pm_enum = getattr(
            PermissionMode,
            PERMISSION_MODE_MAP.get(pm_str, "DEFAULT"),
            PermissionMode.DEFAULT,
        )
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(self._parent_agent.work_dir),
            rule_engine=RuleEngine(),
            mode=pm_enum,
        )

        # 创建子 agent
        sub_agent = AgentClass(
            client=client,
            registry=filtered_registry,
            protocol=self._parent_agent.protocol,
            work_dir=self._parent_agent.work_dir,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=definition.system_prompt,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id

        # 注册追踪节点
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        agent_name = p.name or effective_type or f"agent-{trace_node.agent_id}"

        if is_background:
            if is_fork:
                sub_agent._fork_conversation = conversation
            task_id = self._task_manager.launch(
                agent=sub_agent,
                task="" if is_fork else p.prompt,
                name=agent_name,
                fork_conversation=conversation if is_fork else None,
            )
            return ToolResult(
                output=f"Sub-agent launched in background.\n"
                f"Task ID: {task_id}\n"
                f"Agent: {agent_name}\n"
                f"Type: {definition.agent_type}\n"
                f"The system will notify automatically when it completes.\n"
                f"Do NOT wait, sleep, or poll. Report the task ID to the user and move on.",
            )

        # 前台同步执行
        try:
            if is_fork:
                result_text = await sub_agent.run_to_completion("", conversation)
            else:
                result_text = await sub_agent.run_to_completion(p.prompt)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent failed: {e}", is_error=True
            )

        self._trace_manager.update(
            trace_node.agent_id,
            input_tokens=sub_agent.total_input_tokens,
            output_tokens=sub_agent.total_output_tokens,
        )
        self._trace_manager.complete(trace_node.agent_id, "completed")

        return ToolResult(output=result_text or "(sub-agent returned no output)")

    async def _execute_as_teammate(self, p: AgentToolParams) -> ToolResult:
        if self._team_manager is None:
            return ToolResult(output="TeamManager not configured.", is_error=True)
        if self._worktree_manager is None:
            return ToolResult(output="WorktreeManager not configured for team spawn.", is_error=True)

        from mewcode.agents.fork import ForkError, build_forked_messages
        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import build_teammate_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )
        from mewcode.teams.models import BackendType, TeammateInfo
        from mewcode.teams.registry import AgentNameRegistry

        # 团队不存在就顺手建一个：coordinator 模式下 TeamCreate 不在白名单里，
        # 要求 Lead 先建团队再派人，它会卡在第一步。
        team = self._team_manager.get_team(p.team_name)
        if team is None:
            team = self._team_manager.create_team(
                name=p.team_name,
                lead_agent_id=getattr(self._parent_agent, "agent_id", "lead"),
            )

        base_name = p.name or p.subagent_type or "worker"
        existing_names = {m.name for m in team.members}
        teammate_name = base_name
        if teammate_name in existing_names:
            counter = 2
            while f"{base_name}-{counter}" in existing_names:
                counter += 1
            teammate_name = f"{base_name}-{counter}"

        # 1. 加载 agent 定义
        definition: AgentDef
        conversation: ConversationManager | None = None
        is_fork = False

        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn is None:
                return ToolResult(
                    output=f"Unknown agent type: '{p.subagent_type}'. "
                    f"Available: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
            definition = defn
        else:
            if self._enable_fork:
                try:
                    parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                    if parent_conv is None:
                        return ToolResult(output="Cannot fork: no active conversation.", is_error=True)
                    conversation = build_forked_messages(parent_conv, p.prompt)
                    is_fork = True
                except ForkError as e:
                    return ToolResult(output=str(e), is_error=True)

            definition = AgentDef(
                agent_type="teammate",
                when_to_use="Team member",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",
                max_turns=self._parent_agent.max_iterations,
                permission_mode="bypassPermissions",
                source="builtin",
            )

        # 2. 创建 worktree
        wt_name = f"team-{p.team_name}/{teammate_name}"
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(output=f"Failed to create worktree for teammate: {e}", is_error=True)

        # 3. 选择 LLM
        client = self._select_llm(p, definition)

        # 4. 检测后端类型
        backend = self._team_manager.detect_backend()

        # 5. 构建队友的工具集
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=self._parent_agent.trace_id or self._parent_agent.agent_id,
        )
        agent_id = trace_node.agent_id

        _has_full = getattr(self._parent_agent, '_full_registry', None) is not None
        full_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        _full_tools = [t.name for t in full_registry.list_tools()]
        log.info(
            "[teammate] has_full_registry=%s full_tools=%d names=%s backend=%s def_tools=%s def_disallowed=%s",
            _has_full, len(_full_tools), _full_tools,
            backend.value,
            getattr(definition, 'tools', []),
            getattr(definition, 'disallowed_tools', []),
        )
        teammate_registry = build_teammate_tools(
            parent_registry=full_registry,
            team_manager=self._team_manager,
            team_name=p.team_name,
            agent_id=agent_id,
            agent_name=teammate_name,
            backend_type=backend.value,
            definition=definition,
        )
        _tm_tools = [t.name for t in teammate_registry.list_tools()]
        log.info("[teammate] result_tools=%d names=%s", len(_tm_tools), _tm_tools)

        # 6. 创建子 agent 并附加队友专属指令
        instructions = (definition.system_prompt or "") + TEAMMATE_ADDENDUM

        # 标了 plan_mode_required 的队友以计划模式启动：只能读不能改，
        # 写出计划交 lead 审批，通过后才切回正常权限。
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(wt.path),
            rule_engine=RuleEngine(),
            mode=PermissionMode.PLAN if p.plan_mode_required else PermissionMode.BYPASS,
        )

        sub_agent = AgentClass(
            client=client,
            registry=teammate_registry,
            protocol=self._parent_agent.protocol,
            work_dir=wt.path,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=instructions,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id
        sub_agent.agent_id = agent_id
        sub_agent.team_name = p.team_name
        sub_agent._team_manager = self._team_manager

        # 7. 注册名称和成员信息
        AgentNameRegistry.instance().register(teammate_name, agent_id)

        member = TeammateInfo(
            name=teammate_name,
            agent_id=agent_id,
            agent_type=definition.agent_type,
            model=p.model or definition.model,
            worktree_path=wt.path,
            backend_type=backend.value,
            is_active=True,
            joined_at=int(time.time()),
        )
        self._team_manager.register_member(p.team_name, member)

        # 8. 按后端类型启动队友
        if backend in (BackendType.TMUX, BackendType.ITERM2):
            return self._spawn_pane_teammate(
                p, team, member, backend, wt, agent_id, teammate_name
            )

        # 进程内模式：直接用 task_manager 执行并通知结果
        task_id = self._task_manager.launch(
            agent=sub_agent,
            task="" if is_fork else p.prompt,
            name=teammate_name,
            fork_conversation=conversation if is_fork else None,
        )

        return ToolResult(
            output=(
                f"Teammate '{teammate_name}' spawned in team '{p.team_name}'.\n"
                f"Agent ID: {agent_id}\n"
                f"Backend: {backend.value}\n"
                f"Worktree: {wt.path}\n"
                f"Task ID: {task_id}\n"
                f"The system will notify when it completes."
            )
        )


    def _spawn_pane_teammate(
        self, p: Any, team: Any, member: Any, backend: Any, wt: Any,
        agent_id: str, teammate_name: str,
    ) -> ToolResult:
        from mewcode.teams.models import BackendType
        from mewcode.teams.spawn import build_teammate_cli

        # 外部进程通过邮箱领取初始任务：spawn 前先把任务投进队友邮箱（按队友名字为键），
        # 新进程启动后第一次空闲轮询就能看到工作。
        mailbox = self._team_manager.get_mailbox(p.team_name)
        if mailbox is not None and p.prompt:
            from mewcode.teams.mailbox import create_message
            from mewcode.teams.spawn_inprocess import LEAD_NAME
            mailbox.write(
                teammate_name,
                create_message(
                    from_agent=LEAD_NAME,
                    text=p.prompt,
                ),
            )

        # 构造把本 mewcode 拉起为队友 worker 模式的命令，cd 到该队友的 worktree
        cli_command = build_teammate_cli(p.team_name, teammate_name, wt.path)

        try:
            if backend == BackendType.TMUX:
                from mewcode.teams.spawn_tmux import spawn_tmux_teammate
                pane_info = spawn_tmux_teammate(
                    team_name=p.team_name,
                    member_name=teammate_name,
                    cli_command=cli_command,
                )
                self._team_manager.register_pane_id(agent_id, pane_info.pane_id)
            elif backend == BackendType.ITERM2:
                from mewcode.teams.spawn_iterm2 import spawn_iterm2_teammate
                pane_info = spawn_iterm2_teammate(
                    team_name=p.team_name,
                    member_name=teammate_name,
                    cli_command=cli_command,
                )
                self._team_manager.register_pane_id(agent_id, pane_info.session_id)
        except Exception as e:
            log.warning("Pane spawn failed, falling back to in-process: %s", e)
            return ToolResult(
                output=f"Pane spawn failed ({e}), teammate not started. Retry or set teammate_mode to in-process.",
                is_error=True,
            )

        return ToolResult(
            output=(
                f"Teammate '{teammate_name}' spawned in team '{p.team_name}'.\n"
                f"Agent ID: {agent_id}\n"
                f"Backend: {backend.value} (pane)\n"
                f"Worktree: {wt.path}\n"
                f"The teammate is running in an independent process."
            )
        )


    def _select_llm(
        self,
        params: AgentToolParams,
        definition: AgentDef,
    ) -> LLMClient:
        from mewcode.agents.parser import AgentDef

        model_override = params.model or (
            definition.model if definition.model != "inherit" else None
        )

        if model_override and model_override != "inherit":
            client = self._create_client_for_model(model_override)
            if client is not None:
                return client

        return self._parent_agent.client


    async def _execute_with_worktree(self, p: AgentToolParams) -> ToolResult:
        if self._worktree_manager is None:
            return ToolResult(
                output="Worktree isolation is not available: WorktreeManager not configured.",
                is_error=True,
            )

        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import resolve_agent_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )
        from mewcode.worktree.integration import (
            build_worktree_notice,
            generate_worktree_name,
        )

        definition: AgentDef | None = None
        if p.subagent_type:
            definition = self._agent_loader.get(p.subagent_type)
            if definition is None:
                return ToolResult(
                    output=f"Unknown agent type: '{p.subagent_type}'. "
                    f"Available types: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
        else:
            definition = AgentDef(
                agent_type="worktree-agent",
                when_to_use="Isolated worktree agent",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",
                max_turns=self._parent_agent.max_iterations,
                permission_mode="bypassPermissions",
                source="builtin",
            )

        wt_name = generate_worktree_name()
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(
                output=f"Failed to create worktree: {e}",
                is_error=True,
            )

        notice = build_worktree_notice(self._parent_agent.work_dir, wt.path)
        task = notice + "\n\n" + p.prompt

        client = self._select_llm(p, definition)

        _base_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        filtered_registry = resolve_agent_tools(
            _base_registry, definition, False
        )

        pm_str = definition.permission_mode
        pm_enum = getattr(
            PermissionMode,
            PERMISSION_MODE_MAP.get(pm_str, "DEFAULT"),
            PermissionMode.DEFAULT,
        )
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(wt.path),
            rule_engine=RuleEngine(),
            mode=pm_enum,
        )

        sub_agent = AgentClass(
            client=client,
            registry=filtered_registry,
            protocol=self._parent_agent.protocol,
            work_dir=wt.path,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=definition.system_prompt,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        try:
            result_text = await sub_agent.run_to_completion(task)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent in worktree failed: {e}",
                is_error=True,
            )

        self._trace_manager.update(
            trace_node.agent_id,
            input_tokens=sub_agent.total_input_tokens,
            output_tokens=sub_agent.total_output_tokens,
        )
        self._trace_manager.complete(trace_node.agent_id, "completed")

        cleanup = await self._worktree_manager.auto_cleanup(wt_name, wt.head_commit)
        if cleanup.kept:
            result_text = (result_text or "") + (
                f"\n[Worktree preserved at {cleanup.path}, branch {cleanup.branch}]"
            )

        return ToolResult(output=result_text or "(sub-agent returned no output)")


    def _create_client_for_model(self, model_alias: str) -> LLMClient | None:
        if self._provider_config is None:
            return None

        from mewcode.client import create_client
        from mewcode.config import ProviderConfig

        model_map = {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-6-20250514",
            "opus": "claude-opus-4-6-20250514",
        }
        model_id = model_map.get(model_alias, model_alias)

        config = ProviderConfig(
            name=f"sub-{model_alias}",
            protocol=self._provider_config.protocol,
            base_url=self._provider_config.base_url,
            model=model_id,
            api_key=self._provider_config.api_key,
            context_window=self._provider_config.context_window,
        )
        try:
            return create_client(config)
        except Exception:
            return None
