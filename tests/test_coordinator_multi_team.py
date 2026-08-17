# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

# 回归测试：Coordinator Mode 的工具限制在多 Team 场景下保持稳定。
# 模式由配置在启动时决定，建团队和拆团队都不改变工具集，
# 所以不存在「删掉其中一个团队就提前恢复全部工具」这类时序问题。

from __future__ import annotations

import asyncio
import shutil
from unittest.mock import MagicMock

from koko_pi_agent.agents.tool_filter import apply_coordinator_filter
from koko_pi_agent.teams.manager import TeamManager
from koko_pi_agent.teams.models import resolve_team_dir
from koko_pi_agent.tools.team_create import TeamCreateTool, TeamCreateParams
from koko_pi_agent.tools.team_delete import TeamDeleteTool, TeamDeleteParams
from koko_pi_agent.tools import ToolRegistry
from koko_pi_agent.tools.base import Tool, ToolResult


class DummyTool(Tool):
    params_model = MagicMock

    def __init__(self, name: str, category: str = "read"):
        self.name = name
        self.description = f"Dummy {name}"
        self.category = category
        self.is_concurrency_safe = True

    def get_schema(self):
        return {"name": self.name, "description": self.description, "input_schema": {}}

    async def execute(self, params):
        return ToolResult(output=f"{self.name} executed")


def make_registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(DummyTool(n))
    return reg


class FakeAgent:
    """替身 Agent，coordinator_mode 与真 Agent 一样只看配置开关。"""

    def __init__(self, registry):
        self.agent_id = "lead-1"
        self.enable_coordinator_mode = False
        self.registry = registry

    @property
    def coordinator_mode(self) -> bool:
        return self.enable_coordinator_mode


def cleanup(*names):
    for n in names:
        d = resolve_team_dir(n)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def test_tool_set_stays_narrow_across_team_lifecycle():
    """建团队、拆团队都不该动工具集，收窄只由配置决定。"""
    cleanup("coordbug1", "coordbug2")
    try:
        tm = TeamManager()
        agent = FakeAgent(make_registry("Agent", "WriteFile", "Bash"))
        # 启动时按配置收窄一次
        agent.enable_coordinator_mode = True
        agent.registry = apply_coordinator_filter(agent.registry)
        narrowed = {t.name for t in agent.registry.list_tools()}

        create = TeamCreateTool(tm, agent, teammate_mode="in-process",
                                is_interactive=False, enable_coordinator_mode=True)
        asyncio.run(create.execute(TeamCreateParams(team_name="coordbug1")))
        asyncio.run(create.execute(TeamCreateParams(team_name="coordbug2")))
        assert {t.name for t in agent.registry.list_tools()} == narrowed

        delete = TeamDeleteTool(tm, agent)
        asyncio.run(delete.execute(TeamDeleteParams(team_name="coordbug1")))
        asyncio.run(delete.execute(TeamDeleteParams(team_name="coordbug2")))
        assert {t.name for t in agent.registry.list_tools()} == narrowed
        assert agent.coordinator_mode is True
    finally:
        cleanup("coordbug1", "coordbug2")


def test_disabled_config_leaves_tools_untouched():
    cleanup("coordbug3")
    try:
        tm = TeamManager()
        agent = FakeAgent(make_registry("Agent", "WriteFile", "Bash"))
        create = TeamCreateTool(tm, agent, teammate_mode="in-process",
                                is_interactive=False, enable_coordinator_mode=False)
        asyncio.run(create.execute(TeamCreateParams(team_name="coordbug3")))

        names = {t.name for t in agent.registry.list_tools()}
        assert "WriteFile" in names and "Bash" in names
        assert agent.coordinator_mode is False
    finally:
        cleanup("coordbug3")
