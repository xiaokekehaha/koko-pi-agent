# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import os

from mewcode.commands.registry import Command, CommandContext, CommandType


VERSION = "v0.9.0"


async def handle_status(ctx: CommandContext) -> None:
    lines = ["MewCode 状态", "─────────────"]

    mode = ctx.agent.permission_mode.value if ctx.agent else "unknown"
    lines.append(f"模式: {mode}")

    if ctx.session:
        m = ctx.session.meta
        lines.append(f"会话: {m.id}（{m.message_count} 条消息）")
    else:
        lines.append("会话: 无")

    input_tokens, output_tokens = ctx.ui.get_token_count()
    context_window = ctx.agent.context_window if ctx.agent else 200_000
    pct = int(input_tokens / context_window * 100) if context_window else 0
    lines.append(f"Token: {input_tokens:,} / {context_window:,}（{pct}%）")

    if ctx.agent:
        enabled = [t for t in ctx.agent.registry.list_tools()
                   if ctx.agent.registry.is_enabled(t.name)]
        lines.append(f"工具: {len(enabled)} 个已启用")


    if ctx.memory_manager:
        mem_entries = ctx.memory_manager.get_memories()
        lines.append(f"记忆: {len(mem_entries)} 条")

    work_dir = ctx.agent.work_dir if ctx.agent else os.getcwd()
    lines.append(f"工作目录: {work_dir}")
    lines.append(f"版本: {VERSION}")

    ctx.ui.add_system_message("\n".join(lines))


STATUS_COMMAND = Command(
    name="status",
    aliases=["s"],
    description="显示状态信息",
    usage="/status",
    type=CommandType.LOCAL,
    handler=handle_status,
)

