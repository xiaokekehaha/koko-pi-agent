# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""/mcp 命令的测试：状态展示与手动重连。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from koko_pi_agent.commands.handlers.mcp import handle_mcp
from koko_pi_agent.commands.registry import CommandContext
from koko_pi_agent.mcp.manager import ServerStatus


class FakeUI:
    def __init__(self, manager: Any = None) -> None:
        self.messages: list[str] = []
        self.mcp_manager = manager

    def add_system_message(self, text: str) -> None:
        self.messages.append(text)

    def send_user_message(self, text: str) -> None: ...
    def set_plan_mode(self, enabled: bool) -> None: ...
    def get_token_count(self) -> tuple[int, int]:
        return 0, 0
    def refresh_status(self) -> None: ...
    def show_mascot(self) -> None: ...


def _ctx(args: str, ui: FakeUI, tools: list[str] | None = None) -> CommandContext:
    registry = MagicMock()
    registry.list_tools.return_value = [
        SimpleNamespace(name=n) for n in (tools or [])
    ]
    agent = MagicMock()
    agent.registry = registry
    return CommandContext(
        args=args,
        agent=agent,
        conversation=MagicMock(),
        session=MagicMock(),
        session_manager=MagicMock(),
        memory_manager=MagicMock(),
        ui=ui,
        config=MagicMock(),
    )


def _text(ui: FakeUI) -> str:
    return "\n".join(ui.messages)


class TestMCPStatusDisplay:
    @pytest.mark.asyncio
    async def test_shows_failed_server_with_reason(self) -> None:
        manager = MagicMock()
        manager.list_status.return_value = [
            ServerStatus(
                name="context7",
                connected=False,
                error="Connection closed\nnpm error code ENOTEMPTY",
            )
        ]
        ui = FakeUI(manager)
        await handle_mcp(_ctx("", ui))

        out = _text(ui)
        assert "context7" in out
        assert "ENOTEMPTY" in out, "失败原因必须显示出来"
        assert "reconnect" in out, "应提示可以重连"

    @pytest.mark.asyncio
    async def test_shows_connected_server_tools(self) -> None:
        manager = MagicMock()
        manager.list_status.return_value = [
            ServerStatus(name="context7", connected=True, tool_count=2)
        ]
        ui = FakeUI(manager)
        await handle_mcp(
            _ctx("", ui, tools=["mcp__context7__query-docs", "Bash"])
        )

        out = _text(ui)
        assert "context7" in out
        assert "query-docs" in out
        assert "Bash" not in out

    @pytest.mark.asyncio
    async def test_no_manager(self) -> None:
        ui = FakeUI(None)
        await handle_mcp(_ctx("", ui))
        assert "No MCP servers" in _text(ui)


class TestMCPReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_named_server(self) -> None:
        manager = MagicMock()
        manager.list_status.return_value = [
            ServerStatus(name="context7", connected=False, error="boom")
        ]
        manager.reconnect = AsyncMock(
            return_value=ServerStatus(name="context7", connected=True, tool_count=2)
        )
        ui = FakeUI(manager)
        ctx = _ctx("reconnect context7", ui)

        await handle_mcp(ctx)

        manager.reconnect.assert_awaited_once_with("context7", ctx.agent.registry)
        assert "2" in _text(ui)

    @pytest.mark.asyncio
    async def test_reconnect_all_when_no_name(self) -> None:
        manager = MagicMock()
        manager.server_names.return_value = ["a", "b"]
        manager.reconnect = AsyncMock(
            side_effect=lambda name, _r: ServerStatus(
                name=name, connected=True, tool_count=1
            )
        )
        ui = FakeUI(manager)
        await handle_mcp(_ctx("reconnect", ui))

        assert manager.reconnect.await_count == 2

    @pytest.mark.asyncio
    async def test_reconnect_reports_failure(self) -> None:
        manager = MagicMock()
        manager.reconnect = AsyncMock(
            return_value=ServerStatus(
                name="context7", connected=False, error="npm error E404\nnot found"
            )
        )
        ui = FakeUI(manager)
        await handle_mcp(_ctx("reconnect context7", ui))

        out = _text(ui)
        assert "E404" in out

    @pytest.mark.asyncio
    async def test_reconnect_unknown_server(self) -> None:
        manager = MagicMock()
        manager.reconnect = AsyncMock(return_value=None)
        ui = FakeUI(manager)
        await handle_mcp(_ctx("reconnect nope", ui))

        assert "nope" in _text(ui)

    @pytest.mark.asyncio
    async def test_refuses_while_agent_is_running(self) -> None:
        """回复进行中改动工具表会让本轮工具集前后不一致。"""
        manager = MagicMock()
        manager.reconnect = AsyncMock()
        ui = FakeUI(manager)

        async def _forever() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(_forever())
        ui._agent_task = task
        try:
            await handle_mcp(_ctx("reconnect", ui))
        finally:
            task.cancel()

        manager.reconnect.assert_not_awaited()
        assert "等" in _text(ui)
