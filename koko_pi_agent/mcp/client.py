# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque
from contextlib import AsyncExitStack
from typing import Any, TextIO

import httpx
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from koko_pi_agent.config import MCPServerConfig, build_child_env, resolve_env_vars

logger = logging.getLogger(__name__)

# 连接失败时最多回显多少行子进程 stderr
_STDERR_TAIL_LINES = 40
# 抛错前留给 drain 线程追上子进程临终输出的时间
_STDERR_SETTLE_SECONDS = 0.05


class MCPConnectionError(RuntimeError):
    """连接 MCP 服务器失败。

    消息里附带子进程 stderr 的末尾若干行——传输层只会给出
    "Connection closed" 这类无信息量的错误，真正的原因（npm 安装失败、
    缺少 API key、命令不存在）只出现在子进程 stderr 上。
    """


class _StderrTail:
    """收集 stdio 子进程 stderr 的末尾若干行，用于诊断连接失败。

    stdio_client 会把 errlog 直接交给 ``anyio.open_process(stderr=...)``，
    所以它必须是带 fileno() 的真实文件对象，不能是自定义的 file-like。
    这里用一个管道：写端给子进程，读端由后台线程 drain 进有界 deque。
    """

    def __init__(self, max_lines: int = _STDERR_TAIL_LINES) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self.closed = False
        read_fd, write_fd = os.pipe()
        self._writer = os.fdopen(write_fd, "w", buffering=1, errors="replace")
        self._reader = os.fdopen(read_fd, "r", errors="replace")
        self._thread = threading.Thread(
            target=self._drain, name="mcp-stderr-tail", daemon=True
        )
        self._thread.start()

    @property
    def writer(self) -> TextIO:
        """交给子进程的写端。"""
        return self._writer

    def _drain(self) -> None:
        try:
            for line in self._reader:
                stripped = line.rstrip("\n")
                if stripped:
                    self._lines.append(stripped)
        except (OSError, ValueError):
            # 关闭时读端被抽走属于正常退出路径
            pass

    def text(self) -> str:
        return "\n".join(self._lines)

    def close(self) -> None:
        self.closed = True
        for handle in (self._writer, self._reader):
            try:
                handle.close()
            except Exception:
                pass


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.name = config.name
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._alive = False
        # 存储 MCP 服务器的 InitializeResult，用于提取 instructions 等元信息
        self._init_result: types.InitializeResult | None = None
        self._stderr_tail: _StderrTail | None = None


    @property
    def is_alive(self) -> bool:
        return self._alive

    @property
    def instructions(self) -> str:
        """返回 MCP 服务器的 instructions（来自 InitializeResult）。"""
        if self._init_result is not None and self._init_result.instructions:
            return self._init_result.instructions
        return ""


    async def connect(self) -> None:
        if self._alive:
            return

        # 上一轮连接可能留下未回收的 stack：调用失败会把 client 标记为
        # dead 但不动 stack，此时直接新建会让旧 stdio 子进程无人回收。
        await self._cleanup_stack()

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        try:
            if self.config.is_stdio:
                read, write = await self._connect_stdio()
            else:
                read, write = await self._connect_http()

            session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            # 保存 InitializeResult，后续可从中提取 instructions
            self._init_result = await session.initialize()
            self._session = session
            self._alive = True
            logger.info("MCP server '%s' connected", self.name)
        except Exception as error:
            detail = await self._collect_stderr_detail()
            await self._cleanup_stack()
            if detail:
                raise MCPConnectionError(f"{error}\n{detail}") from error
            raise


    async def _connect_stdio(self) -> tuple[Any, Any]:
        assert self._stack is not None
        assert self.config.command is not None

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=build_child_env(self.config.env),
        )
        tail = _StderrTail()
        self._stderr_tail = tail
        self._stack.callback(tail.close)
        read, write = await self._stack.enter_async_context(
            stdio_client(params, errlog=tail.writer)
        )
        return read, write

    async def _collect_stderr_detail(self) -> str:
        """取回子进程 stderr 末尾，供失败信息使用。"""
        tail = self._stderr_tail
        if tail is None:
            return ""
        # drain 线程可能还没消费完子进程退出前写下的最后几行
        await asyncio.sleep(_STDERR_SETTLE_SECONDS)
        text = tail.text()
        if not text:
            return ""
        return f"--- {self.name} stderr ---\n{text}"

    async def _connect_http(self) -> tuple[Any, Any]:
        assert self._stack is not None
        assert self.config.url is not None

        resolved_headers = {
            k: resolve_env_vars(v) for k, v in self.config.headers.items()
        }
        http_client = httpx.AsyncClient(
            headers=resolved_headers,
            follow_redirects=True,
        )
        await self._stack.enter_async_context(http_client)

        result = await self._stack.enter_async_context(
            streamable_http_client(self.config.url, http_client=http_client)
        )
        read, write = result[0], result[1]
        return read, write


    async def list_tools(self) -> list[types.Tool]:
        assert self._session is not None
        result = await self._session.list_tools()
        return list(result.tools)


    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        assert self._session is not None
        return await self._session.call_tool(name, arguments)

    def mark_dead(self) -> None:
        """标记连接已失效，下次调用时会触发重连。"""
        self._alive = False

    async def reconnect(self) -> None:
        """先回收旧连接再重连，避免遗留子进程。"""
        await self.close()
        await self.connect()

    async def close(self) -> None:
        self._alive = False
        self._session = None
        await self._cleanup_stack()

    async def _cleanup_stack(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.__aexit__(None, None, None)
            except RuntimeError as e:
                if "cancel scope" in str(e):
                    logger.debug("Cancel scope cleanup (expected during shutdown): %s", e)
                else:
                    raise
            except Exception:
                logger.debug("Error closing stack for '%s'", self.name, exc_info=True)
            self._stack = None
