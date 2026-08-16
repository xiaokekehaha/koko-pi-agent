from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mewcode.context import CompactEvent
from mewcode.conversation import ConversationManager, Message
from mewcode.hooks.engine import HookNotification
from mewcode.runtime.events import CompactNotification
from mewcode.runtime.turn_preparer import TurnPreparer


class _Cancellation:
    def __init__(self) -> None:
        self.checked = False

    @property
    def cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        self.checked = True


class _Registry:
    def __init__(self) -> None:
        self.schema_reads = 0

    def get_deferred_tool_names(self) -> list[str]:
        return ["DeferredRead"]

    def get_all_schemas(self, protocol: str) -> list[dict[str, Any]]:
        assert protocol == "anthropic"
        self.schema_reads += 1
        return [{"name": "VisibleTool"}]


class _Hooks:
    def __init__(self) -> None:
        self._notifications = [
            HookNotification(
                hook_id="context-hook",
                event="pre_send",
                output="hook note",
                success=True,
            )
        ]

    def get_prompt_messages(self) -> list[str]:
        return ["hook prompt"]

    def drain_notifications(self) -> list[HookNotification]:
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications


def _agent(tmp_path: Path) -> SimpleNamespace:
    registry = _Registry()

    async def run_hook(event: str, emit, **kwargs) -> None:
        assert event == "pre_send"

    def consume_mailbox(conversation: ConversationManager) -> None:
        conversation.add_user_message("mailbox message")

    return SimpleNamespace(
        _agent_catalog_list=[],
        _consume_mailbox=consume_mailbox,
        _run_hook=run_hook,
        _transcript_path="",
        client=object(),
        compact_breaker=object(),
        context_window=200_000,
        coordinator_mode=False,
        hook_engine=_Hooks(),
        instructions_content="project rules",
        memory_manager=None,
        notification_fn=lambda: ["runtime notification"],
        permission_checker=None,
        plan_mode=False,
        protocol="anthropic",
        recovery_state=object(),
        registry=registry,
        session_dir=tmp_path,
    )


@pytest.mark.asyncio
async def test_prepare_owns_model_context_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def no_compaction(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "mewcode.runtime.turn_preparer.auto_compact",
        no_compaction,
    )
    agent = _agent(tmp_path)
    conversation = ConversationManager()
    cancellation = _Cancellation()
    events = []

    async def emit(event) -> None:
        events.append(event)

    prepared = await TurnPreparer(agent, "environment").prepare(
        conversation,
        2,
        emit,
        cancellation,
    )

    contents = [message.content for message in conversation.history]
    assert contents[0] == "mailbox message"
    assert "runtime notification" in contents[1]
    assert "hook note" in contents[2]
    assert "DeferredRead" in contents[3]
    assert "hook prompt" in prepared.system_prompt
    assert prepared.tool_schemas == ({"name": "VisibleTool"},)
    assert agent.registry.schema_reads == 2
    assert cancellation.checked is True
    assert events == []


@pytest.mark.asyncio
async def test_prepare_reinjects_context_after_compaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def compact(conversation: ConversationManager, *args, **kwargs):
        conversation.replace_history([Message(role="user", content="summary")])
        return CompactEvent(before_tokens=12_345)

    monkeypatch.setattr(
        "mewcode.runtime.turn_preparer.auto_compact",
        compact,
    )
    agent = _agent(tmp_path)
    agent.hook_engine = None
    agent.notification_fn = None
    agent._consume_mailbox = lambda conversation: None
    agent.memory_manager = SimpleNamespace(load=lambda: "remember this")
    conversation = ConversationManager()
    events = []

    async def emit(event) -> None:
        events.append(event)

    await TurnPreparer(agent, "environment").prepare(
        conversation,
        1,
        emit,
        _Cancellation(),
    )

    assert [message.content for message in conversation.history][0] == "environment"
    assert "project rules" in conversation.history[1].content
    assert "remember this" in conversation.history[1].content
    assert conversation.history[2].content == "summary"
    assert len(events) == 1
    assert isinstance(events[0], CompactNotification)
    assert events[0].before_tokens == 12_345
