# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""队友 worker 进程的工具集测试。

队友进程自己组装工具集，和进程内队员那份很容易各改各的，所以这里把清单钉死：
协作工具必须在，团队管理和子 Agent 必须不在。
"""

from __future__ import annotations

import pytest

from mewcode.__main__ import _build_teammate_registry
from pydantic import BaseModel

from mewcode.teams.manager import TeamManager
from mewcode.tools import ToolRegistry
from mewcode.tools.base import Tool


@pytest.mark.asyncio
async def test_teammate_registry_exposes_collaboration_tools(tmp_path, monkeypatch):
    # 团队目录默认落在用户主目录下，指到临时目录避免污染真实配置
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    registry = await _build_teammate_registry(
        work_dir=str(tmp_path),
        protocol="anthropic",
        team_manager=TeamManager(),
        team_name="alpha",
        agent_name="ann",
        mcp_servers=[],
    )
    names = {t.name for t in registry.list_tools()}

    # 干活的工具、通用能力，以及队友之间协作要用的消息和共享任务板
    must_have = {
        "ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep",
        "ToolSearch", "SyntheticOutput", "EnterWorktree", "ExitWorktree",
        "SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
    }
    assert must_have <= names, f"队友工具集缺少 {must_have - names}"

    # 派人和建团队是 Lead 的职责，队友拿不到
    assert not ({"Agent", "TeamCreate", "TeamDelete"} & names)


class _StubTool(Tool):
    """只为过滤测试用的占位工具，execute 不会被调用。"""

    params_model = BaseModel

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name

    async def execute(self, params):  # pragma: no cover - 过滤测试不会调用
        raise NotImplementedError


def test_teammate_tools_block_team_management():
    """进程内队友从 Lead 的注册表过滤而来，团队成员管理工具不能继承过去。"""
    from mewcode.agents.tool_filter import build_teammate_tools
    from mewcode.teams.models import BackendType

    parent = ToolRegistry()
    for name in ["ReadFile", "Bash", "EditFile", "Agent", "TeamCreate", "TeamDelete"]:
        parent.register(_StubTool(name))

    for backend in (BackendType.IN_PROCESS.value, BackendType.TMUX.value):
        reg = build_teammate_tools(
            parent_registry=parent,
            team_manager=TeamManager(),
            team_name="alpha",
            agent_id="ann",
            agent_name="ann",
            backend_type=backend,
        )
        names = {t.name for t in reg.list_tools()}

        # 派人和建团队是 Lead 的职责，队友拿不到
        assert not ({"Agent", "TeamCreate", "TeamDelete"} & names), f"backend={backend}"
        # 协作工具照常注入
        assert {"SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate"} <= names
