# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mewcode.commands.registry import Command, CommandContext, CommandType

if TYPE_CHECKING:
    from mewcode.agents.trace import TraceManager


def _format_elapsed(start: float, end: float | None) -> str:
    elapsed = (end or time.monotonic()) - start
    if elapsed >= 60:
        return f"{elapsed / 60:.1f}m"
    return f"{elapsed:.0f}s"


def _status_icon(status: str) -> str:
    return {"running": "⏳", "completed": "✓", "failed": "✗"}.get(status, "?")


def create_trace_command(trace_manager: TraceManager, lead_agent_id: str = "") -> Command:


    async def handler(ctx: CommandContext) -> None:
        nodes = list(trace_manager._nodes.values())
        if not nodes:
            ctx.ui.add_system_message("没有 Agent 追踪记录")
            return

        parent_map: dict[str | None, list] = {}
        for n in nodes:
            parent_map.setdefault(n.parent_id, []).append(n)

        lines = ["Agent 追踪树:"]


        def _render(parent_id: str | None, indent: int) -> None:
            children = parent_map.get(parent_id, [])
            for n in children:
                icon = _status_icon(n.status)
                elapsed = _format_elapsed(n.start_time, n.end_time)
                tokens = f"↑{n.input_tokens} ↓{n.output_tokens}" if n.input_tokens or n.output_tokens else ""
                prefix = "  " * indent
                lines.append(
                    f"{prefix}{icon} [{n.agent_id[:8]}] {n.agent_type} — {n.status} ({elapsed}) {tokens}"
                )
                _render(n.agent_id, indent + 1)

        roots = [n for n in nodes if n.parent_id is None or n.parent_id not in trace_manager._nodes]
        if not roots:
            roots = nodes[:1]

        if lead_agent_id:
            lines.append(f"  Lead: {lead_agent_id[:8]}")

        for root in roots:
            icon = _status_icon(root.status)
            elapsed = _format_elapsed(root.start_time, root.end_time)
            tokens = f"↑{root.input_tokens} ↓{root.output_tokens}" if root.input_tokens or root.output_tokens else ""
            lines.append(f"  {icon} [{root.agent_id[:8]}] {root.agent_type} — {root.status} ({elapsed}) {tokens}")
            _render(root.agent_id, 2)

        total_in = sum(n.input_tokens for n in nodes)
        total_out = sum(n.output_tokens for n in nodes)
        lines.append(f"\n  合计: {len(nodes)} agents, ↑{total_in} ↓{total_out}")

        ctx.ui.add_system_message("\n".join(lines))

    return Command(
        name="trace",
        description="查看 Agent 父子追踪树（/trace）",
        type=CommandType.LOCAL,
        handler=handler,
        aliases=["tree"],
        usage="/trace",
    )
