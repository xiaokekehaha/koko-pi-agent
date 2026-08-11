# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""验证 /clear 命令正确重置所有会话级状态。"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from mewcode.commands.registry import CommandContext, UIController
from mewcode.commands.handlers.clear import handle_clear
from mewcode.conversation import ConversationManager
from mewcode.memory.session import SessionManager


class MockUI:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def add_system_message(self, text: str) -> None:
        self.messages.append(text)

    def refresh_status(self) -> None:
        pass


class MockAgent:
    def __init__(self, work_dir: str) -> None:
        self._work_dir = work_dir
        self._loop_count = 5
        self.total_input_tokens = 12345
        self.total_output_tokens = 6789
        self.file_history = None
        self.session_id = "old-session"
        self._active_skills: dict[str, str] = {"test": "body"}
        self.registry = MagicMock()
        self.registry.list_tools.return_value = []

    def clear_active_skills(self) -> None:
        self._active_skills.clear()


@pytest.mark.asyncio
async def test_clear_resets_session_id(tmp_path) -> None:
    tmpdir = str(tmp_path)
    sm = SessionManager(tmpdir)
    old_session = sm.create()
    old_id = old_session.session_id

    agent = MockAgent(tmpdir)
    ui = MockUI()

    new_session_holder: list = []

    def set_session(s):
        new_session_holder.append(s)
        agent.session_id = s.session_id

    ctx = CommandContext(
        args="",
        agent=agent,
        conversation=ConversationManager(),
        session=old_session,
        session_manager=sm,
        memory_manager=None,
        ui=ui,
        config={
            "set_session": set_session,
            "set_conversation": lambda c: None,
            "clear_chat": lambda: None,
        },
    )

    await handle_clear(ctx)

    assert len(new_session_holder) == 1, "应创建新 session"
    assert new_session_holder[0].session_id != old_id, "新 session ID 应不同"
    assert agent.session_id != old_id, "agent 的 session_id 应已更新"


@pytest.mark.asyncio
async def test_clear_resets_token_counts(tmp_path) -> None:
    tmpdir = str(tmp_path)
    sm = SessionManager(tmpdir)
    session = sm.create()
    agent = MockAgent(tmpdir)

    ctx = CommandContext(
        args="",
        agent=agent,
        conversation=ConversationManager(),
        session=session,
        session_manager=sm,
        memory_manager=None,
        ui=MockUI(),
        config={
            "set_session": lambda s: None,
            "set_conversation": lambda c: None,
            "clear_chat": lambda: None,
        },
    )

    await handle_clear(ctx)

    assert agent.total_input_tokens == 0, "input tokens 应归零"
    assert agent.total_output_tokens == 0, "output tokens 应归零"


@pytest.mark.asyncio
async def test_clear_resets_loop_count_and_skills(tmp_path) -> None:
    tmpdir = str(tmp_path)
    sm = SessionManager(tmpdir)
    session = sm.create()
    agent = MockAgent(tmpdir)
    agent._active_skills = {"skill1": "body1"}

    ctx = CommandContext(
        args="",
        agent=agent,
        conversation=ConversationManager(),
        session=session,
        session_manager=sm,
        memory_manager=None,
        ui=MockUI(),
        config={
            "set_session": lambda s: None,
            "set_conversation": lambda c: None,
            "clear_chat": lambda: None,
        },
    )

    await handle_clear(ctx)

    assert agent._loop_count == 0, "loop count 应归零"
    assert len(agent._active_skills) == 0, "active skills 应清空"
