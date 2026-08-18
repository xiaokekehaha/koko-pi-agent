# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from typing import Any

from koko_pi_agent.commands.registry import Command, CommandContext, CommandType

# 失败原因（通常带子进程 stderr）最多回显多少行
_ERROR_PREVIEW_LINES = 8
# 单个 server 最多列出多少个工具名
_TOOL_PREVIEW = 10


def _indent_error(error: str) -> list[str]:
    lines = [line for line in error.splitlines() if line.strip()]
    preview = lines[:_ERROR_PREVIEW_LINES]
    out = [f"      {line}" for line in preview]
    remaining = len(lines) - len(preview)
    if remaining > 0:
        out.append(f"      … 还有 {remaining} 行")
    return out


def _server_tool_names(registry: Any, server_name: str) -> list[str]:
    prefix = f"mcp__{server_name}__"
    return [
        tool.name[len(prefix) :]
        for tool in registry.list_tools()
        if tool.name.startswith(prefix)
    ]


def _agent_is_busy(ui: Any) -> bool:
    task = getattr(ui, "_agent_task", None)
    return task is not None and not task.done()


def _show_status(ctx: CommandContext, manager: Any) -> None:
    statuses = list(manager.list_status())
    if not statuses:
        ctx.ui.add_system_message("No MCP servers connected")
        return

    lines = ["MCP 状态", "─────────────"]
    for status in statuses:
        if status.connected and not status.error:
            lines.append(f"  ✓ {status.name}: {status.tool_count} tools")
            tool_names = _server_tool_names(ctx.agent.registry, status.name)
            for name in tool_names[:_TOOL_PREVIEW]:
                lines.append(f"      - {name}")
            if len(tool_names) > _TOOL_PREVIEW:
                lines.append(f"      … and {len(tool_names) - _TOOL_PREVIEW} more")
        else:
            lines.append(f"  ✗ {status.name}: 连接失败")
            lines.extend(_indent_error(status.error))

    lines.append("")
    lines.append("重连：/mcp reconnect [name]")
    ctx.ui.add_system_message("\n".join(lines))


async def _reconnect(ctx: CommandContext, manager: Any, names: list[str]) -> None:
    if _agent_is_busy(ctx.ui):
        ctx.ui.add_system_message("请等当前回复结束后再重连 MCP 服务器")
        return

    targets = names or list(manager.server_names())
    if not targets:
        ctx.ui.add_system_message("No MCP servers configured")
        return

    for name in targets:
        ctx.ui.add_system_message(f"正在重连 MCP 服务器 '{name}' …")
        status = await manager.reconnect(name, ctx.agent.registry)
        if status is None:
            ctx.ui.add_system_message(f"未找到 MCP 服务器 '{name}'")
        elif status.connected and not status.error:
            ctx.ui.add_system_message(
                f"✓ {name} 已重连，注册 {status.tool_count} 个工具"
            )
        else:
            lines = [f"✗ {name} 重连失败"] + _indent_error(status.error)
            ctx.ui.add_system_message("\n".join(lines))


async def handle_mcp(ctx: CommandContext) -> None:
    manager = getattr(ctx.ui, "mcp_manager", None)
    if manager is None:
        ctx.ui.add_system_message("No MCP servers configured")
        return

    parts = ctx.args.split()
    if parts and parts[0] == "reconnect":
        await _reconnect(ctx, manager, parts[1:])
        return

    _show_status(ctx, manager)


MCP_COMMAND = Command(
    name="mcp",
    aliases=[],
    description="显示 MCP 服务器状态，或重连服务器",
    usage="/mcp [reconnect [name]]",
    type=CommandType.LOCAL,
    handler=handle_mcp,
)
