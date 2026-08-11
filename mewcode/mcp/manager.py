# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mewcode.config import MCPServerConfig
from mewcode.mcp.client import MCPClient
from mewcode.mcp.tool_wrapper import MCPToolWrapper
from mewcode.tools import ToolRegistry
from mewcode.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class ServerInfo:
    """单个 MCP 服务器的连接信息，包含名称和 instructions。"""
    name: str
    instructions: str = ""


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

            except Exception as e:
                msg = f"MCP server '{name}': {e}"
                logger.warning(msg)
                result.errors.append(msg)

        return result

    async def register_all_tools(self, registry: ToolRegistry) -> ConnectResult:
        """连接所有服务器并注册工具到 registry，返回 ConnectResult。

        与旧版签名兼容（之前返回 list[str]），现在返回 ConnectResult，
        调用方可通过 result.errors 获取错误列表，也可通过 result.servers
        获取每个服务器的 instructions。
        """
        result = await self.connect_all()
        for tool in result.tools:
            registry.register(tool)
        return result


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
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("MCP server '%s' closed", name)
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)
        self._clients.clear()
