from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from koko_pi_agent.context import CompactEvent, auto_compact
from koko_pi_agent.conversation import ConversationManager
from koko_pi_agent.prompts import (
    build_plan_mode_reminder,
    build_system_prompt,
)
from koko_pi_agent.runtime.events import (
    CompactNotification,
    ErrorEvent,
    EventSink,
)


class _CancellationToken(Protocol):
    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True)
class PreparedModelCall:
    system_prompt: str
    tool_schemas: tuple[dict[str, Any], ...]


class TurnPreparer:
    """Prepare the conversation and projection for one model call."""

    def __init__(self, agent: Any, environment_context: str) -> None:
        self._agent = agent
        self._environment_context = environment_context

    async def prepare(
        self,
        conversation: ConversationManager,
        turn: int,
        emit: EventSink,
        cancellation: _CancellationToken,
    ) -> PreparedModelCall:
        await self._consume_runtime_inputs(conversation, emit)
        system_prompt = self._build_system_prompt()
        self._add_mode_reminders(conversation, turn)
        self._add_hook_notifications(conversation)
        self._add_deferred_tool_reminder(conversation)

        tool_schemas = self._agent.registry.get_all_schemas(self._agent.protocol)
        await self._compact_conversation(conversation, tool_schemas, emit)
        cancellation.raise_if_cancelled()

        # Project schemas again at the final model-call boundary.
        return PreparedModelCall(
            system_prompt=system_prompt,
            tool_schemas=tuple(
                self._agent.registry.get_all_schemas(self._agent.protocol)
            ),
        )

    async def _consume_runtime_inputs(
        self,
        conversation: ConversationManager,
        emit: EventSink,
    ) -> None:
        agent = self._agent
        agent._consume_mailbox(conversation)
        if agent.notification_fn:
            for note in agent.notification_fn():
                conversation.add_system_reminder(note)
        await agent._run_hook("pre_send", emit)

    def _build_system_prompt(self) -> str:
        hook_engine = self._agent.hook_engine
        hook_prompts = hook_engine.get_prompt_messages() if hook_engine else None
        return build_system_prompt(hook_prompts=hook_prompts)

    def _add_mode_reminders(
        self,
        conversation: ConversationManager,
        turn: int,
    ) -> None:
        agent = self._agent
        if agent.plan_mode:
            plan_path = agent._get_plan_path()
            if agent.permission_checker:
                agent.permission_checker.plan_file_path = str(plan_path)
            conversation.add_system_reminder(
                build_plan_mode_reminder(str(plan_path), plan_path.exists(), turn)
            )

        if not agent.coordinator_mode:
            return
        from koko_pi_agent.teams.coordinator import get_coordinator_reminder

        conversation.add_system_reminder(
            get_coordinator_reminder(
                turn,
                agent_catalog=agent._agent_catalog_list or None,
            )
        )

    def _add_hook_notifications(self, conversation: ConversationManager) -> None:
        hook_engine = self._agent.hook_engine
        if not hook_engine:
            return
        for note in hook_engine.drain_notifications():
            conversation.add_system_reminder(
                f"Hook [{note.hook_id}] {note.event}: {note.output}"
            )

    def _add_deferred_tool_reminder(
        self,
        conversation: ConversationManager,
    ) -> None:
        deferred_names = self._agent.registry.get_deferred_tool_names()
        if not deferred_names:
            return
        conversation.add_system_reminder(
            "The following deferred tools are available via ToolSearch. "
            "Their schemas are NOT loaded - use ToolSearch with "
            'query "select:<name>[,<name>...]" to load tool schemas before '
            "calling them:\n"
            + "\n".join(deferred_names)
        )

    async def _compact_conversation(
        self,
        conversation: ConversationManager,
        tool_schemas: list[dict[str, Any]],
        emit: EventSink,
    ) -> None:
        agent = self._agent
        compact_result = await auto_compact(
            conversation,
            agent.client,
            agent.context_window,
            agent.session_dir,
            protocol=agent.protocol,
            breaker=agent.compact_breaker,
            recovery=agent.recovery_state,
            tool_schemas=tool_schemas,
            transcript_path=agent._transcript_path,
        )
        if isinstance(compact_result, CompactEvent):
            await emit(
                CompactNotification(
                    before_tokens=compact_result.before_tokens,
                    message=(
                        "上下文已压缩（压缩前 "
                        f"{compact_result.before_tokens:,} tokens）"
                    ),
                    boundary=compact_result.boundary,
                )
            )
            conversation.inject_environment(self._environment_context)
            memory_content = agent.memory_manager.load() if agent.memory_manager else ""
            conversation.inject_long_term_memory(
                agent.instructions_content,
                memory_content,
            )
        elif isinstance(compact_result, str):
            await emit(ErrorEvent(message=compact_result))
