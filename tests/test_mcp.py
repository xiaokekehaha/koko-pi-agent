# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""MCP 客户端系统的测试（第 6 章）。"""
from __future__ import annotations

import asyncio
import os
import textwrap
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from koko_pi_agent.config import (
    AppConfig,
    ConfigError,
    MCPServerConfig,
    build_child_env,
    load_config,
    resolve_env_vars,
)

# ===========================================================================
# resolve_env_vars
# ===========================================================================

class TestResolveEnvVars:

    def test_substitutes_existing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert resolve_env_vars("${MY_TOKEN}") == "secret123"

    def test_preserves_missing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert resolve_env_vars("${NONEXISTENT_VAR}") == "${NONEXISTENT_VAR}"

    def test_no_placeholder_passthrough(self) -> None:
        assert resolve_env_vars("plain-text") == "plain-text"

    def test_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        assert resolve_env_vars("${A}-${B}") == "hello-world"

    def test_mixed_existing_and_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXISTS", "yes")
        monkeypatch.delenv("NOPE", raising=False)
        assert resolve_env_vars("${EXISTS}/${NOPE}") == "yes/${NOPE}"

# ===========================================================================
# build_child_env
# ===========================================================================

class TestBuildChildEnv:
    def test_includes_path(self) -> None:
        env = build_child_env(None)
        assert "PATH" in env

    def test_includes_declared_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_SECRET", "abc")
        env = build_child_env({"TOKEN": "${MY_SECRET}"})
        assert env["TOKEN"] == "abc"
        assert "PATH" in env

    def test_excludes_host_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        env = build_child_env({"FOO": "bar"})
        assert "ANTHROPIC_API_KEY" not in env
        assert env["FOO"] == "bar"

    def test_empty_declared_env(self) -> None:
        env = build_child_env({})
        assert "PATH" in env

    def test_inherits_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺 HOME 时 npm/npx 找不到 ~/.npmrc 与缓存，行为随平台漂移。"""
        monkeypatch.setenv("HOME", "/home/tester")
        assert build_child_env(None)["HOME"] == "/home/tester"

    def test_inherits_proxy_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """必须走代理才能出网的环境里，剥掉代理会让子进程静默失败。"""
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10900")
        monkeypatch.setenv("NO_PROXY", "localhost")
        env = build_child_env(None)
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:10900"
        assert env["NO_PROXY"] == "localhost"

    def test_inherits_tls_ca_bundle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/etc/ca.pem")
        assert build_child_env(None)["NODE_EXTRA_CA_CERTS"] == "/etc/ca.pem"

    @pytest.mark.parametrize(
        "secret_var",
        [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "NPM_CONFIG__AUTHTOKEN",
        ],
    )
    def test_never_leaks_credentials(
        self, monkeypatch: pytest.MonkeyPatch, secret_var: str
    ) -> None:
        """白名单以外的宿主变量一律不进子进程——MCP server 是第三方代码。"""
        monkeypatch.setenv(secret_var, "sk-should-not-leak")
        env = build_child_env({"FOO": "bar"})
        assert secret_var not in env
        assert "sk-should-not-leak" not in env.values()

    def test_declared_env_still_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """用户在配置里显式声明的变量优先于继承值。"""
        monkeypatch.setenv("HOME", "/home/tester")
        env = build_child_env({"HOME": "/custom"})
        assert env["HOME"] == "/custom"

# ===========================================================================
# load_config：解析 mcp_servers
# ===========================================================================

class TestLoadConfigMCP:
    def _write_config(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent(content))
        return p

    def test_no_mcp_servers(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
        """)
        config = load_config(path)
        assert config.mcp_servers == []

    def test_stdio_server(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: github
                command: npx
                args: ["-y", "@modelcontextprotocol/server-github"]
                env:
                  GITHUB_TOKEN: "${GITHUB_TOKEN}"
        """)
        config = load_config(path)
        assert len(config.mcp_servers) == 1
        srv = config.mcp_servers[0]
        assert srv.name == "github"
        assert srv.command == "npx"
        assert srv.is_stdio is True
        assert srv.args == ["-y", "@modelcontextprotocol/server-github"]

    def test_http_server(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: remote
                url: "https://api.example.com/mcp"
                headers:
                  Authorization: "Bearer ${TOKEN}"
        """)
        config = load_config(path)
        srv = config.mcp_servers[0]
        assert srv.name == "remote"
        assert srv.url == "https://api.example.com/mcp"
        assert srv.is_stdio is False

    def test_both_command_and_url_errors(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                command: npx
                url: "https://example.com"
        """)
        with pytest.raises(ConfigError, match="cannot have both"):
            load_config(path)

    def test_neither_command_nor_url_errors(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                env:
                  FOO: bar
        """)
        with pytest.raises(ConfigError, match="must have either"):
            load_config(path)

# ===========================================================================
# MCPToolWrapper
# ===========================================================================

class TestMCPToolWrapper:
    def test_name_format(self) -> None:
        from mcp import types as mcp_types
        from koko_pi_agent.mcp.tool_wrapper import MCPToolWrapper
        from koko_pi_agent.mcp.client import MCPClient

        tool_def = mcp_types.Tool(
            name="search_issues",
            description="Search GitHub issues",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["repo"],
            },
        )
        mock_client = MagicMock(spec=MCPClient)
        wrapper = MCPToolWrapper("github", tool_def, mock_client)

        assert wrapper.name == "mcp__github__search_issues"
        assert wrapper.category == "command"
        assert wrapper.description == "Search GitHub issues"

    def test_get_schema_uses_original_input_schema(self) -> None:
        from mcp import types as mcp_types
        from koko_pi_agent.mcp.tool_wrapper import MCPToolWrapper

        input_schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        tool_def = mcp_types.Tool(
            name="search",
            description="Search",
            inputSchema=input_schema,
        )
        mock_client = MagicMock()
        wrapper = MCPToolWrapper("srv", tool_def, mock_client)

        schema = wrapper.get_schema()
        assert schema["name"] == "mcp__srv__search"
        assert schema["input_schema"] == input_schema

class TestMCPToolNameContract:
    """生成端与消费端必须用同一套前缀。

    回归背景：wrapper 曾生成单下划线 mcp_{server}_{tool}，而 app.py、
    remote.py、/mcp 命令、tool_filter 四处都按 mcp__{server}__ 匹配，
    导致 /mcp 永远显示 0 tools，且 tool_filter 的「MCP 工具始终放行」失效。
    """

    def _wrapper(self, server: str = "github", tool: str = "search_issues"):
        from mcp import types as mcp_types
        from koko_pi_agent.mcp.tool_wrapper import MCPToolWrapper

        tool_def = mcp_types.Tool(
            name=tool,
            description="d",
            inputSchema={"type": "object", "properties": {}},
        )
        return MCPToolWrapper(server, tool_def, MagicMock())

    def test_tool_filter_recognises_wrapper_name(self) -> None:
        from koko_pi_agent.agents.tool_filter import _is_mcp_tool

        assert _is_mcp_tool(self._wrapper().name) is True

    def test_ui_server_prefix_matches_wrapper_name(self) -> None:
        """app.py / remote.py / handlers/mcp.py 用的过滤前缀。"""
        wrapper = self._wrapper(server="context7", tool="query-docs")
        assert wrapper.name.startswith("mcp__context7__")
        assert wrapper.name.replace("mcp__context7__", "") == "query-docs"

    def test_server_name_boundary_is_unambiguous(self) -> None:
        """server 名自带下划线时，边界依然可解析。"""
        wrapper = self._wrapper(server="my_server", tool="do_thing")
        assert wrapper.name == "mcp__my_server__do_thing"
        assert wrapper.name.startswith("mcp__my_server__")


# ===========================================================================
# _extract_text
# ===========================================================================

class TestExtractText:
    def test_text_content(self) -> None:
        from mcp import types as mcp_types
        from koko_pi_agent.mcp.tool_wrapper import _extract_text

        content = [
            mcp_types.TextContent(type="text", text="hello"),
            mcp_types.TextContent(type="text", text="world"),
        ]
        assert _extract_text(content) == "hello\nworld"

    def test_empty_content(self) -> None:
        from koko_pi_agent.mcp.tool_wrapper import _extract_text

        assert _extract_text([]) == "(no output)"

    def test_image_content(self) -> None:
        from mcp import types as mcp_types
        from koko_pi_agent.mcp.tool_wrapper import _extract_text

        content = [mcp_types.ImageContent(type="image", data="...", mimeType="image/png")]
        assert "[image: image/png]" in _extract_text(content)

# ===========================================================================
# MCPManager：部分失败容错
# ===========================================================================

class TestMCPManagerPartialFailure:
    @pytest.mark.asyncio
    async def test_single_server_failure_does_not_block_others(self) -> None:
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        good_config = MCPServerConfig(
            name="good",
            command="echo",
            args=["hello"],
        )
        bad_config = MCPServerConfig(
            name="bad",
            command="nonexistent_command_xyz_12345",
        )

        manager = MCPManager()
        manager.load_configs([bad_config, good_config])

        registry = ToolRegistry()

        with patch("koko_pi_agent.mcp.manager.MCPClient") as MockClient:
            good_instance = AsyncMock()
            good_instance.is_alive = True

            from mcp import types as mcp_types
            good_instance.list_tools.return_value = [
                mcp_types.Tool(
                    name="test_tool",
                    description="A test",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

            bad_instance = AsyncMock()
            bad_instance.connect.side_effect = RuntimeError("command not found")

            def make_client(config: MCPServerConfig) -> AsyncMock:
                if config.name == "bad":
                    return bad_instance
                return good_instance

            MockClient.side_effect = make_client

            result = await manager.register_all_tools(registry)

        assert len(result.errors) == 1
        assert "bad" in result.errors[0]
        assert registry.get("mcp__good__test_tool") is not None


class _ServerTool:
    description = "MCP manager ownership test tool"
    should_defer = False

    def __init__(self, name: str, server_name: str) -> None:
        self.name = name
        self.server_name = server_name


@pytest.mark.asyncio
async def test_mcp_manager_tracks_provenance_and_unregisters_before_shutdown(
    monkeypatch,
) -> None:
    from koko_pi_agent.mcp.manager import ConnectResult, MCPManager
    from koko_pi_agent.tools import ContributionOwner, ToolRegistry

    registry = ToolRegistry()
    registry.register(
        _ServerTool("Builtin", "builtin"),
        owner=ContributionOwner(
            extension_id="koko_pi_agent.builtin-tools",
            source="builtin",
            runtime_id="runtime-a",
            generation=2,
        ),
    )
    manager = MCPManager()

    async def connect_all() -> ConnectResult:
        return ConnectResult(tools=[_ServerTool("mcp__alpha__search", "alpha")])

    monkeypatch.setattr(manager, "connect_all", connect_all)

    result = await manager.register_all_tools(registry)

    assert result.errors == []
    contribution = registry.list_contributions()[1]
    assert contribution.owner == ContributionOwner(
        extension_id="mcp.alpha",
        source="mcp:alpha",
        runtime_id="runtime-a",
        generation=2,
    )

    await manager.shutdown()
    await manager.shutdown()

    assert [item.name for item in registry.list_contributions()] == ["Builtin"]


@pytest.mark.asyncio
async def test_mcp_registration_conflict_rolls_back_current_batch(monkeypatch) -> None:
    from koko_pi_agent.mcp.manager import ConnectResult, MCPManager
    from koko_pi_agent.tools import ToolRegistry

    registry = ToolRegistry()
    existing = _ServerTool("Existing", "legacy")
    registry.register(existing)
    manager = MCPManager()

    async def connect_all() -> ConnectResult:
        return ConnectResult(
            tools=[
                _ServerTool("First", "alpha"),
                _ServerTool("Existing", "alpha"),
            ]
        )

    monkeypatch.setattr(manager, "connect_all", connect_all)

    result = await manager.register_all_tools(registry)

    assert len(result.errors) == 1
    assert "Existing" in result.errors[0]
    assert registry.get("First") is None
    assert registry.get("Existing") is existing



@pytest.mark.asyncio
async def test_mcp_registration_conflict_does_not_block_later_server(
    monkeypatch,
) -> None:
    from koko_pi_agent.mcp.manager import ConnectResult, MCPManager
    from koko_pi_agent.tools import ToolRegistry

    registry = ToolRegistry()
    original = _ServerTool("Existing", "builtin")
    registry.register(original)
    manager = MCPManager()

    async def connect_all() -> ConnectResult:
        return ConnectResult(
            tools=[
                _ServerTool("First", "alpha"),
                _ServerTool("Existing", "alpha"),
                _ServerTool("Later", "beta"),
            ]
        )

    monkeypatch.setattr(manager, "connect_all", connect_all)

    result = await manager.register_all_tools(registry)

    assert len(result.errors) == 1
    assert registry.get("First") is None
    assert registry.get("Existing") is original
    assert registry.get("Later") is not None

    await manager.shutdown()

    assert registry.get("Later") is None
    assert registry.get("Existing") is original


# ===========================================================================
# MCPClient：子进程 stderr 诊断
# ===========================================================================

class TestClientStderrDiagnostics:
    """连接失败时，子进程的 stderr 必须出现在错误信息里。

    回归背景：errlog 曾被指向 devnull，npx/npm 的真实报错（例如 ENOTEMPTY）
    被完全吞掉，TUI 上只剩一句 "Connection closed"，无法诊断。
    """

    @pytest.mark.asyncio
    async def test_connect_failure_surfaces_child_stderr(self) -> None:
        import sys

        from koko_pi_agent.mcp.client import MCPClient

        config = MCPServerConfig(
            name="broken",
            command=sys.executable,
            args=[
                "-c",
                "import sys; sys.stderr.write('npm error ENOTEMPTY boom\\n'); "
                "sys.exit(1)",
            ],
        )
        client = MCPClient(config)

        with pytest.raises(Exception) as exc_info:
            await client.connect()

        message = str(exc_info.value)
        assert "ENOTEMPTY" in message, f"stderr not surfaced, got: {message!r}"
        assert "broken" in message

    @pytest.mark.asyncio
    async def test_successful_connect_does_not_leak_stderr_thread(self) -> None:
        """stderr 收集器必须随 client 关闭而释放。"""
        from koko_pi_agent.mcp.client import _StderrTail

        tail = _StderrTail()
        tail.writer.write("hello\n")
        tail.writer.flush()
        await asyncio.sleep(0.05)
        assert "hello" in tail.text()

        tail.close()
        assert tail.closed is True


# ===========================================================================
# MCPClient：重连不泄漏子进程
# ===========================================================================

class TestClientReconnect:
    """重连必须先回收上一轮的 AsyncExitStack。

    回归背景：MCPToolWrapper.execute 在 client 被标记为 dead 后直接调
    connect()，而 connect() 会用新的 AsyncExitStack 覆盖旧的，旧 stdio
    子进程从此无人回收——每次调用失败后重连都泄漏一个进程。
    """

    @pytest.mark.asyncio
    async def test_connect_cleans_up_orphaned_stack(self) -> None:
        from contextlib import AsyncExitStack

        from koko_pi_agent.mcp.client import MCPClient

        client = MCPClient(
            MCPServerConfig(name="x", command="nonexistent_command_xyz_12345")
        )

        closed: list[bool] = []
        orphan = AsyncExitStack()
        await orphan.__aenter__()
        orphan.callback(lambda: closed.append(True))
        client._stack = orphan

        with pytest.raises(Exception):
            await client.connect()

        assert closed == [True], "旧 stack 未被回收，子进程会泄漏"

    @pytest.mark.asyncio
    async def test_reconnect_closes_then_connects(self) -> None:
        from koko_pi_agent.mcp.client import MCPClient

        client = MCPClient(MCPServerConfig(name="x", command="true"))
        calls: list[str] = []

        async def fake_close() -> None:
            calls.append("close")

        async def fake_connect() -> None:
            calls.append("connect")

        client.close = fake_close  # type: ignore[method-assign]
        client.connect = fake_connect  # type: ignore[method-assign]

        await client.reconnect()

        assert calls == ["close", "connect"]

    @pytest.mark.asyncio
    async def test_mark_dead_is_public_api(self) -> None:
        """工具包装器不该去改 client 的私有 _alive 字段。"""
        from koko_pi_agent.mcp.client import MCPClient

        client = MCPClient(MCPServerConfig(name="x", command="true"))
        client._alive = True
        client.mark_dead()
        assert client.is_alive is False


# ===========================================================================
# MCPManager：失败 server 的状态保留
# ===========================================================================

class TestMCPManagerStatus:
    """连接失败的 server 必须保留为「可重试」，而不是静默消失。"""

    @pytest.mark.asyncio
    async def test_failed_server_status_is_retained(self) -> None:
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs(
            [MCPServerConfig(name="bad", command="nonexistent_command_xyz_12345")]
        )

        with patch("koko_pi_agent.mcp.manager.MCPClient") as MockClient:
            bad = AsyncMock()
            bad.connect.side_effect = RuntimeError("boom: ENOTEMPTY")
            MockClient.return_value = bad
            await manager.register_all_tools(ToolRegistry())

        status = manager.get_status("bad")
        assert status is not None
        assert status.connected is False
        assert "ENOTEMPTY" in status.error
        assert [s.name for s in manager.list_status()] == ["bad"]

    @pytest.mark.asyncio
    async def test_connected_server_status_records_tool_count(self) -> None:
        from mcp import types as mcp_types

        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs([MCPServerConfig(name="good", command="echo")])

        with patch("koko_pi_agent.mcp.manager.MCPClient") as MockClient:
            good = AsyncMock()
            good.is_alive = True
            good.instructions = ""
            good.list_tools.return_value = [
                mcp_types.Tool(
                    name="t1",
                    description="d",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]
            MockClient.return_value = good
            await manager.register_all_tools(ToolRegistry())

        status = manager.get_status("good")
        assert status is not None
        assert status.connected is True
        assert status.error == ""
        assert status.tool_count == 1


# ===========================================================================
# MCPManager.reconnect
# ===========================================================================

def _fake_client(tool_names: list[str]) -> AsyncMock:
    from mcp import types as mcp_types

    client = AsyncMock()
    client.is_alive = True
    client.instructions = ""
    client.list_tools.return_value = [
        mcp_types.Tool(
            name=name,
            description="d",
            inputSchema={"type": "object", "properties": {}},
        )
        for name in tool_names
    ]
    return client


class TestMCPManagerReconnect:
    """启动时连接失败的 server 必须能在不重启会话的前提下恢复。"""

    @pytest.mark.asyncio
    async def test_reconnect_recovers_from_startup_failure(self) -> None:
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs([MCPServerConfig(name="c7", command="npx")])
        registry = ToolRegistry()

        failing = AsyncMock()
        failing.connect.side_effect = RuntimeError("Connection closed\nENOTEMPTY")

        with patch("koko_pi_agent.mcp.manager.MCPClient", return_value=failing):
            await manager.register_all_tools(registry)

        assert manager.get_status("c7").connected is False
        assert registry.get("mcp__c7__query_docs") is None

        good = _fake_client(["query_docs"])
        with patch("koko_pi_agent.mcp.manager.MCPClient", return_value=good):
            status = await manager.reconnect("c7", registry)

        assert status.connected is True
        assert status.error == ""
        assert status.tool_count == 1
        assert registry.get("mcp__c7__query_docs") is not None

    @pytest.mark.asyncio
    async def test_reconnect_twice_does_not_conflict(self) -> None:
        """重连必须先撤销上一轮的工具注册，否则会撞上重名冲突。"""
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs([MCPServerConfig(name="c7", command="npx")])
        registry = ToolRegistry()

        with patch(
            "koko_pi_agent.mcp.manager.MCPClient",
            return_value=_fake_client(["query_docs"]),
        ):
            await manager.register_all_tools(registry)
            status = await manager.reconnect("c7", registry)

        assert status.connected is True, f"reconnect failed: {status.error}"
        assert status.tool_count == 1
        assert registry.get("mcp__c7__query_docs") is not None
        names = [t.name for t in registry.list_tools()]
        assert names.count("mcp__c7__query_docs") == 1

    @pytest.mark.asyncio
    async def test_reconnect_failure_records_error_without_raising(self) -> None:
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs([MCPServerConfig(name="c7", command="npx")])
        registry = ToolRegistry()

        failing = AsyncMock()
        failing.connect.side_effect = RuntimeError("still broken")

        with patch("koko_pi_agent.mcp.manager.MCPClient", return_value=failing):
            status = await manager.reconnect("c7", registry)

        assert status.connected is False
        assert "still broken" in status.error

    @pytest.mark.asyncio
    async def test_reconnect_unknown_server_returns_none(self) -> None:
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        assert await manager.reconnect("nope", ToolRegistry()) is None

    @pytest.mark.asyncio
    async def test_shutdown_removes_reconnected_tools(self) -> None:
        """重连产生的新 handle 也必须被 shutdown 回收。"""
        from koko_pi_agent.mcp.manager import MCPManager
        from koko_pi_agent.tools import ToolRegistry

        manager = MCPManager()
        manager.load_configs([MCPServerConfig(name="c7", command="npx")])
        registry = ToolRegistry()

        with patch(
            "koko_pi_agent.mcp.manager.MCPClient",
            return_value=_fake_client(["query_docs"]),
        ):
            await manager.register_all_tools(registry)
            await manager.reconnect("c7", registry)

        await manager.shutdown()
        assert registry.get("mcp__c7__query_docs") is None
