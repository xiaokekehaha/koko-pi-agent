# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from koko_pi_agent.config import MCPServerConfig
from koko_pi_agent.mcp.client import MCPClient
from koko_pi_agent.mcp.tool_wrapper import MCPToolWrapper
from koko_pi_agent.tools import (
    ContributionOwner,
    RegistrationHandle,
    ToolRegistry,
)
from koko_pi_agent.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class ServerInfo:
    """单个 MCP 服务器的连接信息，包含名称和 instructions。"""
    name: str
    instructions: str = ""


@dataclass
class ServerStatus:
    """单个 MCP 服务器的当前状态。

    连接失败的服务器也会保留一条记录，这样 /mcp 能把失败原因显示出来，
    用户可以直接重连，而不必重启整个会话。
    """
    name: str
    connected: bool = False
    error: str = ""
    tool_count: int = 0


@dataclass
class ConnectResult:
    """ConnectAll 的返回结果，包含已注册工具、服务器信息和错误列表。"""
    tools: list[Tool] = field(default_factory=list)
    servers: list[ServerInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class MCPManager:


    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._statuses: dict[str, ServerStatus] = {}
        # 按 server 分组：重连时要能只撤销这一个 server 的旧注册
        self._handles_by_server: dict[str, list[RegistrationHandle]] = {}


    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        for cfg in configs:
            self._configs[cfg.name] = cfg


    async def connect_all(self) -> ConnectResult:
        """连接所有已加载的 MCP 服务器，返回工具列表、服务器信息和错误。

        连接后从 InitializeResult 提取 instructions，
        将其包含在 ServerInfo 中返回，供系统提示注入使用。
        """
        result = ConnectResult()
        for name, config in self._configs.items():
            try:
                client = MCPClient(config)
                await client.connect()
                self._clients[name] = client

                # 从 InitializeResult 提取 instructions
                info = ServerInfo(name=name, instructions=client.instructions)
                result.servers.append(info)

                tools = await client.list_tools()
                for tool_def in tools:
                    wrapper = MCPToolWrapper(name, tool_def, client)
                    result.tools.append(wrapper)
                    logger.info("Registered MCP tool: %s", wrapper.name)

                self._statuses[name] = ServerStatus(
                    name=name, connected=True, tool_count=len(tools)
                )

            except Exception as e:
                msg = f"MCP server '{name}': {e}"
                logger.warning(msg)
                result.errors.append(msg)
                self._statuses[name] = ServerStatus(
                    name=name, connected=False, error=str(e)
                )

        return result

    async def register_all_tools(self, registry: ToolRegistry) -> ConnectResult:
        """连接所有服务器并注册工具到 registry，返回 ConnectResult。

        与旧版签名兼容（之前返回 list[str]），现在返回 ConnectResult，
        调用方可通过 result.errors 获取错误列表，也可通过 result.servers
        获取每个服务器的 instructions。
        """
        result = await self.connect_all()
        handles_by_server: dict[str, list[RegistrationHandle]] = {}
        registered_tools: list[Tool] = []
        failed_servers: set[str] = set()
        for tool in result.tools:
            server_name = getattr(
                tool,
                "server_name",
                getattr(tool, "_server_name", "unknown"),
            )
            if server_name in failed_servers:
                continue
            owner = self._owner_for(server_name, registry)
            try:
                handle = registry.register(tool, owner=owner)
            except Exception as error:
                failed_servers.add(server_name)
                server_handles = handles_by_server.pop(server_name, [])
                for registered_handle in reversed(server_handles):
                    registered_handle.close()
                registered_tools = [
                    registered_tool
                    for registered_tool in registered_tools
                    if getattr(
                        registered_tool,
                        "server_name",
                        getattr(registered_tool, "_server_name", "unknown"),
                    )
                    != server_name
                ]
                message = f"MCP server '{server_name}' tool registration: {error}"
                logger.warning(message)
                result.errors.append(message)
                status = self._statuses.get(server_name)
                if status is not None:
                    status.error = str(error)
                    status.tool_count = 0
                continue
            handles_by_server.setdefault(server_name, []).append(handle)
            registered_tools.append(tool)
        result.tools = registered_tools
        for server_name, handles in handles_by_server.items():
            self._handles_by_server.setdefault(server_name, []).extend(handles)
            status = self._statuses.get(server_name)
            if status is not None:
                status.tool_count = len(handles)
        return result

    def _owner_for(self, server_name: str, registry: ToolRegistry) -> ContributionOwner:
        runtime_identity = {
            (contribution.owner.runtime_id, contribution.owner.generation)
            for contribution in registry.list_contributions()
            if contribution.owner.runtime_id
        }
        if len(runtime_identity) == 1:
            runtime_id, generation = next(iter(runtime_identity))
        else:
            runtime_id, generation = "", 0
        return ContributionOwner(
            extension_id=f"mcp.{server_name}",
            source=f"mcp:{server_name}",
            runtime_id=runtime_id,
            generation=generation,
        )

    def _release_server(self, name: str) -> None:
        """撤销某个 server 已注册的全部工具。"""
        for handle in reversed(self._handles_by_server.pop(name, [])):
            handle.close()

    async def reconnect(
        self, name: str, registry: ToolRegistry
    ) -> ServerStatus | None:
        """重连单个 MCP 服务器并重新注册它的工具。

        返回新的状态；服务器名未配置时返回 None。连接失败不抛异常——
        失败原因写进 ServerStatus.error，调用方负责展示。
        """
        config = self._configs.get(name)
        if config is None:
            return None

        self._release_server(name)
        old_client = self._clients.pop(name, None)
        if old_client is not None:
            try:
                await old_client.close()
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)

        client = MCPClient(config)
        try:
            await client.connect()
            tool_defs = await client.list_tools()
        except Exception as error:
            logger.warning("MCP server '%s' reconnect failed: %s", name, error)
            status = ServerStatus(name=name, connected=False, error=str(error))
            self._statuses[name] = status
            return status

        self._clients[name] = client
        handles: list[RegistrationHandle] = []
        owner = self._owner_for(name, registry)
        for tool_def in tool_defs:
            wrapper = MCPToolWrapper(name, tool_def, client)
            try:
                handles.append(registry.register(wrapper, owner=owner))
            except Exception as error:
                for handle in reversed(handles):
                    handle.close()
                message = f"tool registration: {error}"
                logger.warning("MCP server '%s' %s", name, message)
                status = ServerStatus(name=name, connected=True, error=message)
                self._statuses[name] = status
                return status

        self._handles_by_server[name] = handles
        status = ServerStatus(name=name, connected=True, tool_count=len(handles))
        self._statuses[name] = status
        logger.info("MCP server '%s' reconnected, %d tools", name, len(handles))
        return status

    def server_names(self) -> list[str]:
        """所有已配置的 server 名（含从未连上的）。"""
        return list(self._configs)

    def get_status(self, name: str) -> ServerStatus | None:
        return self._statuses.get(name)

    def list_status(self) -> list[ServerStatus]:
        """按配置顺序返回所有已知 server 的状态（含失败的）。"""
        return [
            self._statuses[name]
            for name in self._configs
            if name in self._statuses
        ]


    async def get_client(self, name: str) -> MCPClient | None:
        client = self._clients.get(name)
        if client is None:
            config = self._configs.get(name)
            if config is None:
                return None
            client = MCPClient(config)
            await client.connect()
            self._clients[name] = client
            return client

        if not client.is_alive:
            logger.info("Reconnecting MCP server '%s'", name)
            await client.close()
            client = MCPClient(self._configs[name])
            await client.connect()
            self._clients[name] = client

        return client


    async def shutdown(self) -> None:
        all_handles = [
            handle
            for handles in self._handles_by_server.values()
            for handle in handles
        ]
        for handle in reversed(all_handles):
            handle.close()
        self._handles_by_server.clear()
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("MCP server '%s' closed", name)
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)
            status = self._statuses.get(name)
            if status is not None:
                status.connected = False
                status.tool_count = 0
        self._clients.clear()
