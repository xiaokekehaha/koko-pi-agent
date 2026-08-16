# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""
Remote Control 服务器：通过 WebSocket 桥接 Agent 事件和 Web UI。

使用 websockets 库提供 HTTP（静态 HTML）+ WebSocket 服务，
让用户在浏览器中与 MewCode Agent 交互。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.server import Server as WSServer, ServerConnection
from websockets.http11 import Request, Response

from mewcode.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)
from mewcode.client import create_client, resolve_context_window
from mewcode.commands import CommandContext, CommandRegistry, CommandType
from mewcode.commands.handlers import register_all_commands
from mewcode.commands.parser import parse_command
from mewcode.config import MCPServerConfig, ProviderConfig
from mewcode.conversation import ConversationManager
from mewcode.hooks import HookEngine
from mewcode.mcp import MCPManager
from mewcode.memory import MemoryManager, load_instructions
from mewcode.memory.session import Session, SessionManager
from mewcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mewcode.skills.loader import SkillLoader
from mewcode.tools import ToolRegistry, create_default_registry
from mewcode.tools.impl.tool_search import ToolSearchTool
from mewcode.tools.load_skill import LoadSkill
from mewcode.web_content import INDEX_HTML

log = logging.getLogger(__name__)


class RemoteServer:
    """Remote Control 核心：桥接 Agent 事件和 WebSocket 客户端。"""

    def __init__(
        self,
        providers: list[ProviderConfig],
        mcp_servers: list[MCPServerConfig] | None = None,
        hook_engine: HookEngine | None = None,
        addr: str = "0.0.0.0",
        port: int = 18888,
        config: object | None = None,
    ) -> None:
        self._config = config
        self.providers = providers
        self._mcp_server_configs = mcp_servers or []
        self.hook_engine = hook_engine
        self.addr = addr
        self.port = port

        # WebSocket 连接池（支持多客户端广播）
        self._connections: set[ServerConnection] = set()

        # Agent 相关状态
        self.agent: Agent | None = None
        self.conversation: ConversationManager | None = None
        self.registry: ToolRegistry | None = None
        self.session_id: str = ""
        self._streaming = False
        self._cancel_event: asyncio.Event | None = None

        # 权限请求的 pending 队列：id -> Future
        self._pending_perms: dict[str, asyncio.Future[PermissionResponse]] = {}

        # 命令注册表
        self.command_registry = CommandRegistry()
        register_all_commands(self.command_registry)

        # MCP 相关
        self.mcp_manager: MCPManager | None = None
        self._mcp_instructions: str = ""

        # Skill 加载器
        self.skill_loader: SkillLoader | None = None

        # Memory / Session
        self.memory_manager: MemoryManager | None = None
        self.session_manager: SessionManager | None = None
        self.session: Session | None = None

    # ------------------------------------------------------------------
    # 启动入口
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """启动 HTTP + WebSocket 服务器。"""
        # 初始化 Agent
        self._init_agent()

        # 初始化 MCP（如果有配置）
        await self._init_mcp()

        print(f"\n  Remote UI: http://localhost:{self.port}\n")

        # websockets 的 serve 支持 process_request 回调来处理普通 HTTP
        async with websockets.serve(
            self._ws_handler,
            self.addr,
            self.port,
            process_request=self._process_http_request,
            max_size=4 * 1024 * 1024,  # 4MB 消息上限
        ):
            # 服务器启动后永久阻塞
            await asyncio.Future()

    # ------------------------------------------------------------------
    # HTTP 请求处理（为 / 路径提供前端 HTML）
    # ------------------------------------------------------------------

    def _process_http_request(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        """拦截 HTTP 请求，对 / 路径返回 HTML 页面。
        返回 None 表示继续走 WebSocket 升级流程。
        """
        if request.path == "/":
            return Response(
                200,
                "OK",
                websockets.Headers({"Content-Type": "text/html; charset=utf-8"}),
                INDEX_HTML.encode("utf-8"),
            )
        if request.path != "/ws":
            return Response(404, "Not Found", websockets.Headers(), b"404 Not Found")
        # /ws 路径 → 继续 WebSocket 升级
        return None

    # ------------------------------------------------------------------
    # WebSocket 连接处理
    # ------------------------------------------------------------------

    async def _ws_handler(self, websocket: ServerConnection) -> None:
        """处理单个 WebSocket 连接的全生命周期。"""
        self._connections.add(websocket)
        try:
            # 连接建立时推送会话信息
            await self._broadcast({
                "type": "connected",
                "data": {
                    "session": self.session_id,
                    "cwd": os.getcwd(),
                },
            })

            # 推送命令列表
            await self._broadcast({
                "type": "commands",
                "data": self._build_command_list(),
            })

            # 消息循环
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                data = msg.get("data", {})

                if msg_type == "user_message":
                    content = data.get("content", "").strip()
                    if content:
                        # 在后台任务中处理，不阻塞 WebSocket 读循环
                        asyncio.create_task(self._handle_user_message(content))

                elif msg_type == "permission_response":
                    self._handle_permission_response(data)

                elif msg_type == "cancel":
                    if self._cancel_event is not None:
                        self._cancel_event.set()
                    if self.agent is not None:
                        self.agent.cancel_active_run()

                elif msg_type == "ping":
                    # 应用层保活
                    await self._broadcast({"type": "pong", "data": None})

        except websockets.ConnectionClosed:
            pass
        finally:
            self._connections.discard(websocket)

    # ------------------------------------------------------------------
    # Agent 初始化（复刻 TUI 的 _select_provider 流程）
    # ------------------------------------------------------------------

    def _init_agent(self) -> None:
        """初始化 Agent 及相关子系统。"""
        provider = self.providers[0]
        work_dir = os.getcwd()
        home = Path.home()

        # 权限系统
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(work_dir),
            rule_engine=RuleEngine(
                user_rules_path=home / ".mewcode" / "permissions.yaml",
                project_rules_path=Path(work_dir) / ".mewcode" / "permissions.yaml",
                local_rules_path=Path(work_dir) / ".mewcode" / "permissions.local.yaml",
            ),
            mode=PermissionMode.DEFAULT,
        )

        # 加载自定义指令和记忆
        instructions = load_instructions(work_dir)
        self.memory_manager = MemoryManager(work_dir)
        self.session_manager = SessionManager(work_dir)
        self.session = self.session_manager.create()
        self.session_id = self.session.session_id

        # 创建 LLM 客户端
        client = create_client(provider)

        # 工具注册表
        self.registry = create_default_registry()
        self.registry.register(ToolSearchTool(self.registry, protocol=provider.protocol))

        # Skill 加载
        self.skill_loader = SkillLoader(work_dir)
        self.skill_loader.load_all()
        load_skill_tool = LoadSkill()
        self.registry.register(load_skill_tool)

        # 创建 Agent
        self.agent = Agent(
            client=client,
            registry=self.registry,
            protocol=provider.protocol,
            work_dir=work_dir,
            permission_checker=checker,
            context_window=provider.get_context_window(),
            instructions_content=instructions,
            memory_manager=self.memory_manager,
            hook_engine=self.hook_engine,
        )
        self.agent.session_id = self.session_id

        # 团队工具在 remote 模式下同样可用，Lead 能在浏览器会话里组建团队把活派出去
        from mewcode.agents.loader import AgentLoader
        from mewcode.agents.task_manager import TaskManager
        from mewcode.agents.trace import TraceManager
        from mewcode.config import WorktreeConfig
        from mewcode.teams.manager import TeamManager
        from mewcode.tools.agent_tool import AgentTool
        from mewcode.tools.synthetic_output import SyntheticOutputTool
        from mewcode.tools.task_stop import TaskStopTool
        from mewcode.tools.team_create import TeamCreateTool
        from mewcode.tools.team_delete import TeamDeleteTool
        from mewcode.worktree import WorktreeManager

        cfg = self._config
        enable_fork = getattr(cfg, "enable_fork", False)
        enable_verification = getattr(cfg, "enable_verification_agent", False)
        enable_coordinator = getattr(cfg, "enable_coordinator_mode", False)
        wt_cfg = getattr(cfg, "worktree", None) or WorktreeConfig()

        wt_manager = WorktreeManager(
            repo_root=work_dir,
            symlink_directories=wt_cfg.symlink_directories,
        )
        trace_manager = TraceManager()
        self.task_manager = TaskManager()
        agent_loader = AgentLoader(work_dir, enable_verification=enable_verification)
        agent_loader.load_all()
        self.team_manager = TeamManager(
            worktree_manager=wt_manager, trace_manager=trace_manager
        )

        self.registry.register(AgentTool(
            agent_loader=agent_loader,
            task_manager=self.task_manager,
            trace_manager=trace_manager,
            parent_agent=self.agent,
            enable_fork=enable_fork,
            provider_config=provider,
            worktree_manager=wt_manager,
            team_manager=self.team_manager,
        ))
        self.registry.register(TeamCreateTool(
            team_manager=self.team_manager,
            parent_agent=self.agent,
            teammate_mode="in-process",
            is_interactive=False,
            enable_coordinator_mode=enable_coordinator,
        ))
        self.registry.register(TeamDeleteTool(
            team_manager=self.team_manager, parent_agent=self.agent
        ))
        self.registry.register(TaskStopTool(team_manager=self.team_manager))
        self.registry.register(SyntheticOutputTool())

        # 队员干完活的回传落在 lead 信箱里，每轮排空成 system-reminder 交给 Lead
        self.agent.notification_fn = self.team_manager.drain_lead_mailbox

        # 连接 Skill 到 Agent
        load_skill_tool.set_loader(self.skill_loader)
        load_skill_tool.set_agent(self.agent)

        catalog = self.skill_loader.get_catalog()
        if catalog:
            lines = ["You can use the following Skills:", ""]
            for name, desc in catalog:
                lines.append(f"- {name}: {desc}")
            lines.append("")
            lines.append("If the user's request matches a Skill, call LoadSkill to activate it.")
            self.agent.set_skill_catalog("\n".join(lines))

        # 初始化对话管理器
        self.conversation = ConversationManager()

        log.info("Agent initialized: session=%s, model=%s", self.session_id, provider.model)

    # ------------------------------------------------------------------
    # MCP 初始化
    # ------------------------------------------------------------------

    async def _init_mcp(self) -> None:
        """连接所有配置的 MCP 服务器，注册工具。"""
        if not self._mcp_server_configs or self.registry is None:
            return

        manager = MCPManager()
        manager.load_configs(self._mcp_server_configs)
        connect_result = await manager.register_all_tools(self.registry)
        self.mcp_manager = manager

        for err in connect_result.errors:
            log.warning("MCP error: %s", err)

        # 构建 MCP 指令（首次发送消息时注入 conversation）
        if connect_result.servers:
            parts = []
            for srv_info in connect_result.servers:
                section = f"## {srv_info.name}\n"
                if srv_info.instructions:
                    section += srv_info.instructions
                else:
                    tool_names = [
                        t.name for t in self.registry.list_tools()
                        if t.name.startswith(f"mcp__{srv_info.name}__")
                    ]
                    if tool_names:
                        section += "Available tools: " + ", ".join(tool_names)
                parts.append(section)
            self._mcp_instructions = (
                "# MCP Server Instructions\n\n"
                "The following MCP servers have provided instructions "
                "for how to use their tools and resources:\n\n"
                + "\n\n".join(parts)
            )

    # ------------------------------------------------------------------
    # 用户消息处理
    # ------------------------------------------------------------------

    async def _handle_user_message(self, content: str) -> None:
        """处理来自 Web UI 的用户消息或斜杠命令。"""
        if self._streaming:
            return

        # 斜杠命令
        if content.startswith("/"):
            await self._handle_slash_command(content)
            return

        # 普通消息 → 发给 Agent
        self._streaming = True
        assert self.conversation is not None
        assert self.agent is not None

        self.conversation.add_user_message(content)

        # 首次注入 MCP 指令
        if self._mcp_instructions:
            self.conversation.add_system_reminder(self._mcp_instructions)
            self._mcp_instructions = ""

        # 创建取消事件
        self._cancel_event = asyncio.Event()
        start_time = time.monotonic()
        stream_buf = ""

        try:
            async for event in self.agent.run(self.conversation):
                # 检查取消信号
                if self._cancel_event.is_set():
                    break

                if isinstance(event, StreamText):
                    stream_buf += event.text
                    await self._broadcast({
                        "type": "stream_text",
                        "data": {"text": event.text},
                    })

                elif isinstance(event, ThinkingText):
                    await self._broadcast({
                        "type": "thinking_text",
                        "data": {"text": event.text},
                    })

                elif isinstance(event, ToolUseEvent):
                    await self._broadcast({
                        "type": "tool_use",
                        "data": {
                            "toolId": event.tool_id,
                            "toolName": event.tool_name,
                            "args": event.arguments,
                        },
                    })

                elif isinstance(event, ToolResultEvent):
                    # 如果之前有累积的流式文本，先结束它
                    if stream_buf:
                        await self._broadcast({
                            "type": "stream_end",
                            "data": {"text": stream_buf},
                        })
                        stream_buf = ""
                    await self._broadcast({
                        "type": "tool_result",
                        "data": {
                            "toolId": event.tool_id,
                            "toolName": event.tool_name,
                            "output": event.output,
                            "isError": event.is_error,
                            "elapsed": event.elapsed,
                        },
                    })

                elif isinstance(event, PermissionRequest):
                    # 生成唯一 ID，等待 Web 端回复
                    perm_id = f"perm_{time.time_ns()}"
                    self._pending_perms[perm_id] = event.future
                    await self._broadcast({
                        "type": "permission_request",
                        "data": {
                            "id": perm_id,
                            "toolName": event.tool_name,
                            "description": event.description,
                        },
                    })

                elif isinstance(event, TurnComplete):
                    if stream_buf:
                        await self._broadcast({
                            "type": "stream_end",
                            "data": {"text": stream_buf},
                        })
                        stream_buf = ""
                    await self._broadcast({
                        "type": "turn_complete",
                        "data": {"turn": event.turn},
                    })

                elif isinstance(event, LoopComplete):
                    if stream_buf:
                        await self._broadcast({
                            "type": "stream_end",
                            "data": {"text": stream_buf},
                        })
                        stream_buf = ""
                    elapsed = time.monotonic() - start_time
                    await self._broadcast({
                        "type": "loop_complete",
                        "data": {
                            "totalTurns": event.total_turns,
                            "elapsed": elapsed,
                        },
                    })

                elif isinstance(event, UsageEvent):
                    await self._broadcast({
                        "type": "usage",
                        "data": {
                            "inputTokens": event.input_tokens,
                            "outputTokens": event.output_tokens,
                        },
                    })

                elif isinstance(event, ErrorEvent):
                    await self._broadcast({
                        "type": "error",
                        "data": {"message": event.message},
                    })

                elif isinstance(event, CompactNotification):
                    await self._broadcast({
                        "type": "compact",
                        "data": {"message": event.message},
                    })

                elif isinstance(event, RetryEvent):
                    await self._broadcast({
                        "type": "retry",
                        "data": {
                            "reason": event.reason,
                            "waitMs": int(event.wait * 1000),
                        },
                    })

                elif isinstance(event, HookEvent):
                    status = "ok" if event.success else "error"
                    await self._broadcast({
                        "type": "system",
                        "data": {
                            "message": f"Hook [{event.hook_id}] {status}: {event.output}"
                        },
                    })

        except asyncio.CancelledError:
            await self._broadcast({
                "type": "error",
                "data": {"message": "Operation cancelled"},
            })
        except Exception as exc:
            log.exception("Agent run error")
            await self._broadcast({
                "type": "error",
                "data": {"message": str(exc)},
            })
        finally:
            self._streaming = False
            self._cancel_event = None

    # ------------------------------------------------------------------
    # 斜杠命令处理
    # ------------------------------------------------------------------

    async def _handle_slash_command(self, input_text: str) -> None:
        """分发斜杠命令。"""
        name, args, is_command = parse_command(input_text)
        if not is_command or not name:
            return

        cmd = self.command_registry.find(name)
        if cmd is None:
            await self._broadcast({
                "type": "error",
                "data": {"message": f"Unknown command: /{name} — type /help to see available commands"},
            })
            await self._broadcast({"type": "command_done", "data": None})
            return

        # 需要参数但没给
        if not args and cmd.arg_prompt:
            await self._broadcast({
                "type": "system",
                "data": {"message": cmd.arg_prompt},
            })
            await self._broadcast({"type": "command_done", "data": None})
            return

        if cmd.type == CommandType.LOCAL:
            # 本地命令直接执行
            ctx = self._build_command_context(args)
            try:
                await cmd.handler(ctx)
            except Exception as exc:
                await self._broadcast({
                    "type": "error",
                    "data": {"message": f"Command error: {exc}"},
                })
            await self._broadcast({"type": "command_done", "data": None})

        elif cmd.type == CommandType.LOCAL_UI:
            # UI 命令需要特殊处理
            # Use the resolved command's canonical name here. ``name`` is the
            # raw token parsed from the input and may be an alias (for example
            # /mew or /cat for /mascot).
            if cmd.name == "mascot":
                await self._broadcast({"type": "mascot_show", "data": None})

            elif cmd.name == "clear":
                self.conversation = ConversationManager()
                if self.agent is not None:
                    self.agent.clear_active_skills()
                await self._broadcast({"type": "clear", "data": None})

            elif cmd.name == "compact":
                await self._handle_compact()
                return

            else:
                await self._broadcast({
                    "type": "system",
                    "data": {"message": f"/{name} is not fully supported in remote mode."},
                })

            await self._broadcast({"type": "command_done", "data": None})

        elif cmd.type == CommandType.PROMPT:
            # Prompt 类命令：handler 返回 prompt 文本，注入给 agent
            ctx = self._build_command_context(args)
            try:
                await cmd.handler(ctx)
            except Exception as exc:
                await self._broadcast({
                    "type": "error",
                    "data": {"message": f"Command error: {exc}"},
                })
                await self._broadcast({"type": "command_done", "data": None})

    def _build_command_context(self, args: str) -> CommandContext:
        """构建命令上下文。"""
        return CommandContext(
            args=args,
            agent=self.agent,
            conversation=self.conversation,
            session=self.session,
            session_manager=self.session_manager,
            memory_manager=self.memory_manager,
            ui=self,  # type: ignore[arg-type]
            config={
                "registry": self.command_registry,
            },
        )

    async def _handle_compact(self) -> None:
        """处理 /compact 命令。"""
        if self.agent is None or self.conversation is None:
            await self._broadcast({
                "type": "error",
                "data": {"message": "Compact requires an active agent."},
            })
            await self._broadcast({"type": "command_done", "data": None})
            return

        await self._broadcast({
            "type": "system",
            "data": {"message": "Compacting conversation..."},
        })

        result = await self.agent.manual_compact(self.conversation)
        if isinstance(result, CompactNotification):
            await self._broadcast({
                "type": "system",
                "data": {"message": result.message},
            })
        elif isinstance(result, ErrorEvent):
            await self._broadcast({
                "type": "error",
                "data": {"message": result.message},
            })

        await self._broadcast({"type": "command_done", "data": None})

    # ------------------------------------------------------------------
    # UIController 协议实现（供命令系统回调）
    # ------------------------------------------------------------------

    def add_system_message(self, text: str) -> None:
        """同步接口 — 在事件循环中调度广播。"""
        asyncio.ensure_future(self._broadcast({
            "type": "system",
            "data": {"message": text},
        }))

    def send_user_message(self, text: str) -> None:
        """同步接口 — 注入用户消息并触发 agent。"""
        asyncio.create_task(self._handle_user_message(text))

    def set_plan_mode(self, enabled: bool) -> None:
        if self.agent is None:
            return
        if enabled:
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            self.agent.set_permission_mode(PermissionMode.DEFAULT)

    def get_token_count(self) -> tuple[int, int]:
        if self.agent:
            return self.agent.total_input_tokens, self.agent.total_output_tokens
        return 0, 0

    def refresh_status(self) -> None:
        pass  # Remote 模式不需要刷新 TUI 状态栏

    def show_mascot(self) -> None:
        """Schedule the Web UI event required by the command controller."""
        asyncio.ensure_future(self._broadcast({
            "type": "mascot_show",
            "data": None,
        }))

    # ------------------------------------------------------------------
    # 权限响应处理
    # ------------------------------------------------------------------

    def _handle_permission_response(self, data: dict[str, Any]) -> None:
        """处理来自 Web UI 的权限回复。"""
        perm_id = data.get("id", "")
        response_str = data.get("response", "deny")

        future = self._pending_perms.pop(perm_id, None)
        if future is None or future.done():
            return

        # 映射字符串到枚举
        mapping = {
            "allow": PermissionResponse.ALLOW,
            "deny": PermissionResponse.DENY,
            "allowAlways": PermissionResponse.ALLOW_ALWAYS,
        }
        response = mapping.get(response_str, PermissionResponse.DENY)
        future.set_result(response)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _build_command_list(self) -> list[dict[str, str]]:
        """构建命令列表，推送给前端用于斜杠命令菜单。"""
        result = []
        for cmd in self.command_registry.list_commands():
            result.append({
                "name": cmd.name,
                "description": cmd.description,
            })
        return result

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        """向所有已连接的 WebSocket 客户端广播消息。"""
        if not self._connections:
            return
        data = json.dumps(msg, ensure_ascii=False)
        # 复制集合避免迭代中修改
        closed = []
        for ws in list(self._connections):
            try:
                await ws.send(data)
            except websockets.ConnectionClosed:
                closed.append(ws)
            except Exception:
                closed.append(ws)
        for ws in closed:
            self._connections.discard(ws)
