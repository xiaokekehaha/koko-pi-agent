# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""针对延迟加载（Deferred Loading）/ ToolSearch 机制的测试。"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from mewcode.tools import ToolRegistry
from mewcode.tools.base import Tool, ToolResult
from mewcode.tools.impl.tool_search import ToolSearchTool

# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

class _DummyParams(BaseModel):
    text: str = ""

class _NormalTool(Tool):
    name = "NormalTool"
    description = "A normal, non-deferred tool"
    params_model = _DummyParams
    category = "read"
    should_defer = False

    async def execute(self, params: BaseModel) -> ToolResult:
        return ToolResult(output="ok")

class _DeferredTool(Tool):
    name = "DeferredAlpha"
    description = "A deferred tool for testing"
    params_model = _DummyParams
    category = "read"
    should_defer = True

    async def execute(self, params: BaseModel) -> ToolResult:
        return ToolResult(output="deferred ok")

class _DeferredBeta(Tool):
    name = "DeferredBeta"
    description = "Another deferred tool beta variant"
    params_model = _DummyParams
    category = "read"
    should_defer = True

    async def execute(self, params: BaseModel) -> ToolResult:
        return ToolResult(output="deferred beta ok")

def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_NormalTool())
    reg.register(_DeferredTool())
    reg.register(_DeferredBeta())
    return reg

# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

def test_should_defer_default_false():
    """Tool 基类的 should_defer 默认值应为 False。"""
    tool = _NormalTool()
    assert tool.should_defer is False

def test_mcp_tool_deferred():
    """MCPToolWrapper 在构造时会把 should_defer 设为 True。"""
    # 这里避免导入 mcp 相关类型；改为在一个模拟对象上检查该属性，
    # 该对象模仿了 MCPToolWrapper.__init__ 的行为。
    from unittest.mock import MagicMock

    mock_tool_def = MagicMock()
    mock_tool_def.name = "example"
    mock_tool_def.description = "An MCP tool"
    mock_tool_def.inputSchema = {"type": "object", "properties": {}}

    mock_client = MagicMock()

    from mewcode.mcp.tool_wrapper import MCPToolWrapper

    wrapper = MCPToolWrapper(
        server_name="test_server",
        tool_def=mock_tool_def,
        client=mock_client,
    )
    assert wrapper.should_defer is True

def test_deferred_not_in_schemas():
    """尚未被发现的延迟工具不应出现在 get_all_schemas 的结果中。"""
    reg = _make_registry()
    schemas = reg.get_all_schemas()
    names = {s["name"] for s in schemas}
    assert "NormalTool" in names
    assert "DeferredAlpha" not in names
    assert "DeferredBeta" not in names

@pytest.mark.asyncio
async def test_tool_search_marks_discovered():
    """ToolSearchTool.execute 应将工具标记为已发现。"""
    reg = _make_registry()
    search = ToolSearchTool(reg, protocol="anthropic")
    reg.register(search)

    from mewcode.tools.impl.tool_search import ToolSearchParams

    params = ToolSearchParams(query="select:DeferredAlpha")
    result = await search.execute(params)

    assert not result.is_error
    assert "DeferredAlpha" in result.output
    assert reg.is_discovered("DeferredAlpha")
    assert not reg.is_discovered("DeferredBeta")

def test_discovered_in_schemas():
    """延迟工具一旦被发现，就应出现在 get_all_schemas 的结果中。"""
    reg = _make_registry()
    # 初始时不在 schemas 中
    schemas_before = reg.get_all_schemas()
    names_before = {s["name"] for s in schemas_before}
    assert "DeferredAlpha" not in names_before

    # 标记为已发现
    reg.mark_discovered("DeferredAlpha")

    schemas_after = reg.get_all_schemas()
    names_after = {s["name"] for s in schemas_after}
    assert "DeferredAlpha" in names_after
    # DeferredBeta 仍未被发现
    assert "DeferredBeta" not in names_after

def test_get_deferred_tool_names():
    """get_deferred_tool_names 只返回尚未被发现的延迟工具。"""
    reg = _make_registry()
    deferred = reg.get_deferred_tool_names()
    assert "DeferredAlpha" in deferred
    assert "DeferredBeta" in deferred
    assert "NormalTool" not in deferred

    # 发现其中一个之后
    reg.mark_discovered("DeferredAlpha")
    deferred2 = reg.get_deferred_tool_names()
    assert "DeferredAlpha" not in deferred2
    assert "DeferredBeta" in deferred2

@pytest.mark.asyncio
async def test_tool_search_keyword():
    """ToolSearchTool 的关键词搜索会返回匹配的延迟工具。"""
    reg = _make_registry()
    search = ToolSearchTool(reg, protocol="anthropic")
    reg.register(search)

    from mewcode.tools.impl.tool_search import ToolSearchParams

    params = ToolSearchParams(query="beta", max_results=5)
    result = await search.execute(params)

    assert not result.is_error
    assert "DeferredBeta" in result.output
    assert reg.is_discovered("DeferredBeta")

@pytest.mark.asyncio
async def test_tool_search_no_match():
    """当没有匹配项时，ToolSearchTool 会返回可用的工具名称列表。"""
    reg = _make_registry()
    search = ToolSearchTool(reg, protocol="anthropic")
    reg.register(search)

    from mewcode.tools.impl.tool_search import ToolSearchParams

    params = ToolSearchParams(query="nonexistent_xyz")
    result = await search.execute(params)

    assert "No matching deferred tools" in result.output
    assert "DeferredAlpha" in result.output
    assert "DeferredBeta" in result.output

@pytest.mark.asyncio
async def test_tool_search_select_multiple():
    """select: 语法可以一次性加载多个工具。"""
    reg = _make_registry()
    search = ToolSearchTool(reg, protocol="anthropic")
    reg.register(search)

    from mewcode.tools.impl.tool_search import ToolSearchParams

    params = ToolSearchParams(query="select:DeferredAlpha,DeferredBeta")
    result = await search.execute(params)

    assert not result.is_error
    assert "Found 2 tool(s)" in result.output
    assert reg.is_discovered("DeferredAlpha")
    assert reg.is_discovered("DeferredBeta")

# ---------------------------------------------------------------------------
# 延迟加载：token 节省量与端到端发现流程
# ---------------------------------------------------------------------------

class _HeavyParams(BaseModel):
    """一个包含大量属性的参数模型，用于模拟真实场景下的 schema。"""

    alpha: str = ""
    bravo: str = ""
    charlie: int = 0
    delta: float = 0.0
    echo: bool = False
    foxtrot: str = "default_foxtrot_value"
    golf: str = "default_golf_value"
    hotel: int = 42
    india: str = ""
    juliet: bool = True

def _make_deferred_tool(index: int) -> Tool:
    """动态创建一个具有唯一名称的延迟工具类。"""

    class _T(Tool):
        name = f"DeferredHeavy_{index:03d}"
        description = (
            f"Deferred heavy tool number {index} that provides advanced "
            f"functionality for processing, transforming, and analyzing data "
            f"in context {index}."
        )
        params_model = _HeavyParams
        category = "read"
        should_defer = True

        async def execute(self, params: BaseModel) -> ToolResult:
            return ToolResult(output=f"heavy {index}")

    return _T()

def test_deferred_token_savings():
    """对于 50 个重型工具，延迟加载应能节省至少 90% 的 schema token。"""
    import json

    reg = ToolRegistry()

    # 2 个普通工具
    reg.register(_NormalTool())

    class _Normal2(Tool):
        name = "NormalTool2"
        description = "Second normal tool"
        params_model = _DummyParams
        category = "read"
        should_defer = False

        async def execute(self, params: BaseModel) -> ToolResult:
            return ToolResult(output="ok2")

    reg.register(_Normal2())

    # 50 个带有真实 schema 的延迟工具
    deferred_names: list[str] = []
    for i in range(50):
        tool = _make_deferred_tool(i)
        reg.register(tool)
        deferred_names.append(tool.name)

    # 测量延迟工具被隐藏时的大小
    schemas_deferred = reg.get_all_schemas("anthropic")
    size_deferred = len(json.dumps(schemas_deferred))

    # 发现全部延迟工具
    for name in deferred_names:
        reg.mark_discovered(name)

    # 测量所有工具都可见时的大小
    schemas_all = reg.get_all_schemas("anthropic")
    size_all = len(json.dumps(schemas_all))

    savings = 1 - size_deferred / size_all
    print(
        f"\nDeferred token savings: {savings:.1%} "
        f"(deferred={size_deferred}, all={size_all})"
    )
    assert savings >= 0.90, (
        f"Expected >= 90% savings, got {savings:.1%} "
        f"(deferred={size_deferred}, all={size_all})"
    )

def test_deferred_end_to_end_discovery():
    """端到端测试：延迟工具初始处于隐藏状态，被发现后才出现。"""
    reg = ToolRegistry()

    # 1 个普通工具
    reg.register(_NormalTool())

    # 2 个延迟工具
    reg.register(_DeferredTool())   # DeferredAlpha
    reg.register(_DeferredBeta())   # DeferredBeta

    # --- 初始时：延迟工具不出现在 schemas 中 ---
    schemas = reg.get_all_schemas("anthropic")
    schema_names = {s["name"] for s in schemas}
    assert "NormalTool" in schema_names
    assert "DeferredAlpha" not in schema_names
    assert "DeferredBeta" not in schema_names

    # --- get_deferred_tool_names 同时列出两者 ---
    deferred = reg.get_deferred_tool_names()
    assert "DeferredAlpha" in deferred
    assert "DeferredBeta" in deferred

    # --- 发现其中一个 ---
    reg.mark_discovered("DeferredAlpha")

    schemas2 = reg.get_all_schemas("anthropic")
    schema_names2 = {s["name"] for s in schemas2}
    assert "DeferredAlpha" in schema_names2
    assert "DeferredBeta" not in schema_names2

    # --- 此时 get_deferred_tool_names 只返回另一个 ---
    deferred2 = reg.get_deferred_tool_names()
    assert "DeferredAlpha" not in deferred2
    assert "DeferredBeta" in deferred2
