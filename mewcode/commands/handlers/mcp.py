# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_mcp(ctx: CommandContext) -> None:
    app = ctx.ui
    info = getattr(app, "_mcp_server_info", "")
    if not info:
        ctx.ui.add_system_message("No MCP servers connected")
        return

    lines = ["MCP 状态", "─────────────"]
    lines.append(info)

    mcp_mgr = getattr(app, "mcp_manager", None)
    if mcp_mgr and hasattr(mcp_mgr, "_clients"):
        for name, client in mcp_mgr._clients.items():
            tool_names = [
                t.name for t in ctx.agent.registry.list_tools()
                if t.name.startswith(f"mcp__{name}__")
            ]
            lines.append(f"\n  {name}: {len(tool_names)} tools")
            for tn in tool_names[:10]:
                short = tn.replace(f"mcp__{name}__", "")
                lines.append(f"    - {short}")
            if len(tool_names) > 10:
                lines.append(f"    … and {len(tool_names) - 10} more")

    ctx.ui.add_system_message("\n".join(lines))


MCP_COMMAND = Command(
    name="mcp",
    aliases=[],
    description="显示 MCP 服务器状态",
    usage="/mcp",
    type=CommandType.LOCAL,
    handler=handle_mcp,
)
