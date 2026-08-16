from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mewcode.context import CompactEvent, auto_compact
from mewcode.conversation import ConversationManager
from mewcode.prompts import (
    build_plan_mode_reminder,
    build_system_prompt,
)
from mewcode.runtime.events import (
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
        agent = self._agent

        agent._consume_mailbox(conversation)
        if agent.notification_fn:
            for note in agent.notification_fn():
                conversation.add_system_reminder(note)
        await agent._run_hook("pre_send", emit)

        hook_prompts = (
            agent.hook_engine.get_prompt_messages() if agent.hook_engine else None
        )
        system_prompt = build_system_prompt(hook_prompts=hook_prompts)

        if agent.plan_mode:
            plan_path = str(agent._get_plan_path())
            if agent.permission_checker:
                agent.permission_checker.plan_file_path = plan_path
            conversation.add_system_reminder(
                build_plan_mode_reminder(
                    plan_path,
                    agent._get_plan_path().exists(),
                    turn,
                )
            )

        if agent.coordinator_mode:
            from mewcode.teams.coordinator import get_coordinator_reminder

            conversation.add_system_reminder(
                get_coordinator_reminder(
                    turn,
                    agent_catalog=agent._agent_catalog_list or None,
                )
            )

        if agent.hook_engine:
            for note in agent.hook_engine.drain_notifications():
                conversation.add_system_reminder(
                    f"Hook [{note.hook_id}] {note.event}: {note.output}"
                )

        deferred_names = agent.registry.get_deferred_tool_names()
        if deferred_names:
            conversation.add_system_reminder(
                "The following deferred tools are available via ToolSearch. "
                "Their schemas are NOT loaded - use ToolSearch with "
                'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
                + "\n".join(deferred_names)
            )

        tool_schemas = agent.registry.get_all_schemas(agent.protocol)
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
            memory_content = (
                agent.memory_manager.load() if agent.memory_manager else ""
            )
            conversation.inject_long_term_memory(
                agent.instructions_content,
                memory_content,
            )
        elif isinstance(compact_result, str):
            await emit(ErrorEvent(message=compact_result))

        cancellation.raise_if_cancelled()
        return PreparedModelCall(
            system_prompt=system_prompt,
            tool_schemas=tuple(agent.registry.get_all_schemas(agent.protocol)),
        )
