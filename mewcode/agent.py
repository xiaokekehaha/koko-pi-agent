# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from pathlib import Path
from typing import Any

from mewcode.client import LLMClient
from mewcode.context import (
    CompactCircuitBreaker,
    CompactEvent,
    RecoveryState,
    auto_compact,
    ensure_session_dir,
)
from mewcode.conversation import ConversationManager
from mewcode.hooks import HookContext, HookEngine
from mewcode.memory.auto_memory import MemoryManager
from mewcode.permissions import PermissionChecker, PermissionMode
from mewcode.prompts import build_environment_context
from mewcode.runtime.agent_loop import (
    AgentLoop,
    AgentRun,
    RunRequest,
    RunStatus,
    StreamCollector,
    StreamingEventAdapter,
)
from mewcode.runtime.events import (
    AgentEvent,
    CompactNotification,
    ErrorEvent,
    EventSink,
    HookEvent,
    LoopComplete,
    MessageFinished,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    RunFailed,
    RunFinished,
    RunResult,
    RunStarted,
    StreamText,
    ThinkingText,
    ToolExecutionFinished,
    ToolExecutionStarted,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    TurnFinished,
    TurnStarted,
    UsageEvent,
    UsageUpdated,
)
from mewcode.runtime.tool_pipeline import (
    ApprovalAdapter,
    HeadlessApprovalAdapter,
    InteractiveApprovalAdapter,
)
from mewcode.tools import ToolRegistry

log = logging.getLogger(__name__)

__all__ = [
    "Agent",
    "AgentEvent",
    "CompactNotification",
    "ErrorEvent",
    "HookEvent",
    "LoopComplete",
    "MessageFinished",
    "PermissionRequest",
    "PermissionResponse",
    "RetryEvent",
    "RunFailed",
    "RunFinished",
    "RunResult",
    "RunStarted",
    "StreamCollector",
    "StreamText",
    "ThinkingText",
    "ToolExecutionFinished",
    "ToolExecutionStarted",
    "ToolResultEvent",
    "ToolUseEvent",
    "TurnComplete",
    "TurnFinished",
    "TurnStarted",
    "UsageEvent",
    "UsageUpdated",
]

# ---------------------------------------------------------------------------
# Agent 主循环
# ---------------------------------------------------------------------------


class Agent:
    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        protocol: str,
        work_dir: str = ".",
        max_iterations: int = 0,
        permission_checker: PermissionChecker | None = None,
        context_window: int = 200_000,
        instructions_content: str = "",
        memory_manager: MemoryManager | None = None,
        hook_engine: HookEngine | None = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.protocol = protocol
        self.work_dir = work_dir
        self.max_iterations = max_iterations
        self.permission_checker = permission_checker
        self.permission_mode: PermissionMode = (
            permission_checker.mode if permission_checker else PermissionMode.DEFAULT
        )
        self.context_window = context_window
        self.compact_breaker = CompactCircuitBreaker()
        # 保存重建工作上下文所需的快照，在 Layer 2 压缩对话后使用：
        # 最近的文件读取和 skill 调用。每次 ReadFile / skill 调用时记录，
        # auto_compact 触发阈值时消费。
        self.recovery_state: RecoveryState = RecoveryState()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.instructions_content = instructions_content
        self.memory_manager = memory_manager
        self.hook_engine = hook_engine
        self._loop_count = 0
        # 记忆提取合并策略：_extracting 期间触发新请求会标记 _pending_extraction，
        # _extracting: 标记是否有提取正在进行
        # _pending_extraction: 提取期间又触发了新请求，标记需要尾随提取
        self._extracting = False
        self._pending_extraction = False
        self._consolidator: MemoryConsolidator | None = None
        if memory_manager is not None:
            from mewcode.memory.consolidation import MemoryConsolidator

            self._consolidator = MemoryConsolidator(work_dir)
        self.session_id: str = ""
        self.active_skills: dict[str, str] = {}
        self._skill_catalog: str = ""
        self._agent_catalog: str = ""
        self._agent_catalog_list: list[tuple[str, str]] = []
        self.agent_id: str = uuid.uuid4().hex[:12]
        self.parent_id: str | None = None
        self.trace_id: str | None = None
        self.team_name: str = ""
        self._team_manager: Any = None
        # coordinator 模式的开关，由配置显式打开
        self.enable_coordinator_mode: bool = False
        self.notification_fn: Callable[[], list[str]] | None = None
        self.file_history: Any = None

        # 非阻塞 memory recall：prefetch task 与主 LLM 调用并行，工具执行后注入
        self.memory_recall_task: Any | None = None
        self._memory_recall_consumed: bool = False
        self._active_run: AgentRun | None = None

    @property
    def session_dir(self) -> Path:
        # 溢写目录跟随当前会话 id（resume 换会话后自动指向新目录）
        return ensure_session_dir(self.work_dir, self.session_id)

    @property
    def _transcript_path(self) -> str:
        if self.session_id:
            return str(
                Path(self.work_dir)
                / ".mewcode"
                / "sessions"
                / f"{self.session_id}.jsonl"
            )
        return ""

    @property
    def plan_mode(self) -> bool:
        return self.permission_mode == PermissionMode.PLAN

    @property
    def coordinator_mode(self) -> bool:
        """coordinator 模式是否生效，只看配置开关。

        不看团队是否存在：模式在会话中途切换会留下麻烦，已经发出去的调度指引
        留在对话历史里撤不回来，模型会照着过期的约束继续做事。
        配置说了算，从第一轮到最后一轮都是同一套规则。
        """
        return self.enable_coordinator_mode

    _plan_path_cache: Path | None = None

    def _get_plan_path(self) -> Path:
        if self._plan_path_cache is not None:
            return self._plan_path_cache
        import datetime
        import random

        _ADJECTIVES = [
            "bold",
            "bright",
            "calm",
            "cool",
            "deep",
            "fair",
            "fast",
            "fine",
            "glad",
            "keen",
            "kind",
            "lean",
            "mild",
            "neat",
            "pure",
            "safe",
            "slim",
            "soft",
            "tall",
            "warm",
            "wise",
            "grand",
            "swift",
            "vivid",
        ]
        _NOUNS = [
            "sketch",
            "draft",
            "spark",
            "bloom",
            "trail",
            "ridge",
            "creek",
            "grove",
            "cliff",
            "cloud",
            "field",
            "forge",
            "frost",
            "haven",
            "pearl",
            "stone",
            "storm",
            "river",
            "tower",
            "delta",
            "flame",
            "orbit",
            "pulse",
            "shore",
        ]
        plans_dir = Path(self.work_dir) / ".mewcode" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%m%d-%H%M")
        slug = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}-{ts}"
        self._plan_path_cache = plans_dir / f"{slug}.md"
        return self._plan_path_cache

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        if self.permission_checker:
            self.permission_checker.mode = mode

    def activate_skill(self, name: str, prompt_body: str) -> None:
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        self.active_skills.clear()

    def set_skill_catalog(self, catalog: str) -> None:
        self._skill_catalog = catalog

    def set_agent_catalog(
        self, catalog: str, catalog_list: list[tuple[str, str]] | None = None
    ) -> None:
        self._agent_catalog = catalog
        if catalog_list is not None:
            self._agent_catalog_list = catalog_list

    def _build_hook_context(self, event: str, **kwargs: str | dict) -> HookContext:
        return HookContext(
            event_name=event,
            tool_name=str(kwargs.get("tool_name", "")),
            tool_args=kwargs.get("tool_args", {}),
            file_path=str(kwargs.get("file_path", "")),
            message=str(kwargs.get("message", "")),
            error=str(kwargs.get("error", "")),
        )

    def _infer_file_path(self, args: dict) -> str:
        return str(args.get("file_path", args.get("path", "")))

    def _drain_hook_events(self) -> list[HookEvent]:
        if not self.hook_engine:
            return []
        return [
            HookEvent(
                hook_id=n.hook_id,
                event=n.event,
                output=n.output,
                success=n.success,
            )
            for n in self.hook_engine.drain_notifications()
        ]

    async def _run_hook(
        self,
        event: str,
        emit: EventSink,
        **kwargs: str | dict[str, Any],
    ) -> None:
        if self.hook_engine is None:
            return
        context = self._build_hook_context(event, **kwargs)
        await self.hook_engine.run_hooks(event, context)
        for hook_event in self._drain_hook_events():
            await emit(hook_event)

    @property
    def active_run(self) -> AgentRun | None:
        run = self._active_run
        if run is not None and run.status == RunStatus.IDLE:
            return None
        return run

    def start_run(
        self,
        conversation: ConversationManager,
        emit: Callable[[AgentEvent], Awaitable[None]],
        *,
        approval: ApprovalAdapter | None = None,
    ) -> AgentRun:
        if self.active_run is not None:
            raise RuntimeError("Agent already has an active run")
        loop = AgentLoop(
            self,
            approval or InteractiveApprovalAdapter(),
        )

        def clear_active(completed: AgentRun) -> None:
            if self._active_run is completed:
                self._active_run = None

        run = AgentRun(
            loop=loop,
            request=RunRequest(conversation=conversation),
            emit=emit,
            on_idle=clear_active,
        )
        self._active_run = run
        run.start()
        return run

    def cancel_active_run(self) -> None:
        if self.active_run is not None:
            self.active_run.cancel()

    async def run(self, conversation: ConversationManager) -> AsyncIterator[AgentEvent]:
        adapter = StreamingEventAdapter()
        run = self.start_run(
            conversation,
            adapter.emit,
            approval=InteractiveApprovalAdapter(),
        )
        async with aclosing(adapter.events(run)) as events:
            async for event in events:
                yield event

    def _consume_mailbox(self, conversation: ConversationManager) -> None:
        if not self.team_name or not self._team_manager:
            return
        try:
            mailbox = self._team_manager.get_mailbox(self.team_name)
            if mailbox is None:
                return
            messages = mailbox.consume(self.agent_id)
            for msg in messages:
                prefix = f"[Message from {msg.from_agent}]"
                if msg.type != "text":
                    prefix = f"[{msg.type} from {msg.from_agent}]"
                content = f"{prefix} {msg.text}"
                conversation.add_user_message(content)
        except Exception as e:
            log.debug("Mailbox consumption failed: %s", e)

    async def _extract_memories(self, conversation: ConversationManager) -> None:
        """触发记忆提取，合并策略见类内字段注释。

        当提取正在进行时，新的触发不会启动并发提取，而是标记 _pending_extraction。
        当前提取完成后检查该标志，如果有 pending 则立即执行一次尾随提取，
        防止多个触发器同时执行导致重复提取。
        """
        if not self.memory_manager:
            return

        # 合并策略：正在提取时暂存新请求，等当前提取完成后尾随执行
        if self._extracting:
            log.debug(
                "[extractMemories] extraction in progress — stashing for trailing run"
            )
            self._pending_extraction = True
            return

        self._extracting = True
        try:
            await self.memory_manager.extract(self.client, conversation, self.protocol)
        except Exception as e:
            log.debug("Memory extraction failed: %s", e)
        finally:
            self._extracting = False
            # 检查是否有尾随提取请求
            if self._pending_extraction:
                self._pending_extraction = False
                log.debug(
                    "[extractMemories] running trailing extraction for stashed context"
                )
                # 递归调用自身处理尾随请求
                await self._extract_memories(conversation)

    async def manual_compact(
        self, conversation: ConversationManager
    ) -> CompactNotification | ErrorEvent:
        # auto_compact 会用摘要替换 conversation.history，所有 tool-result 内容
        # （原始或已替换的）都将被丢弃。这里跳过 apply_tool_result_budget —
        # 它在主循环中的唯一目的是为 LLM 调用生成 api_conv，而本路径不需要
        # 发起看到替换结果的 LLM 调用（auto_compact 内部的摘要调用操作的是原始对话）。
        result = await auto_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            protocol=self.protocol,
            manual=True,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
            transcript_path=self._transcript_path,
        )
        if isinstance(result, CompactEvent):
            env_context = build_environment_context(
                self.work_dir,
                self.active_skills,
                self._skill_catalog,
                self._agent_catalog,
            )
            conversation.inject_environment(env_context)
            memory_content = self.memory_manager.load() if self.memory_manager else ""
            conversation.inject_long_term_memory(
                self.instructions_content, memory_content
            )
            return CompactNotification(
                before_tokens=result.before_tokens,
                message=f"上下文已压缩（压缩前 {result.before_tokens:,} tokens）",
                boundary=result.boundary,
            )
        return ErrorEvent(message=result or "压缩失败：对话历史为空或未达到压缩条件")

    async def run_to_completion(
        self,
        task: str,
        conversation: ConversationManager | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        if conversation is None:
            conversation = ConversationManager()
        if task:
            conversation.add_user_message(task)

        async def emit(event: AgentEvent) -> None:
            if event_callback is None:
                return
            if isinstance(event, MessageFinished) and event.text:
                event_callback({"type": "stream_text", "text": event.text})
            elif isinstance(event, ToolUseEvent):
                event_callback(
                    {
                        "type": "tool_use",
                        "toolName": event.tool_name,
                        "args": event.arguments,
                    }
                )
            elif isinstance(event, ToolResultEvent):
                event_callback(
                    {
                        "type": "tool_result",
                        "toolName": event.tool_name,
                        "output": event.output,
                        "isError": event.is_error,
                    }
                )
            elif isinstance(event, UsageEvent):
                event_callback(
                    {
                        "type": "usage",
                        "usage": {
                            "inputTokens": event.input_tokens,
                            "outputTokens": event.output_tokens,
                        },
                    }
                )
            elif isinstance(event, ErrorEvent):
                event_callback({"type": "error", "message": event.message})

        run = self.start_run(
            conversation,
            emit,
            approval=HeadlessApprovalAdapter(self.permission_mode),
        )
        try:
            result = await run.wait_until_idle()
        except asyncio.CancelledError:
            run.cancel()
            await run.wait_until_idle()
            raise
        if result.status == "failed":
            raise RuntimeError(result.error or "Agent run failed")
        return result.final_text
