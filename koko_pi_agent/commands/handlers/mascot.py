from __future__ import annotations

from koko_pi_agent.commands.registry import Command, CommandContext, CommandType


async def handle_mascot(ctx: CommandContext) -> None:
    """Show the UI mascot without changing the conversation or session."""
    ctx.ui.show_mascot()


MASCOT_COMMAND = Command(
    name="mascot",
    aliases=["mew", "cat"],
    description="显示可拖拽的 ASCII 柯基动画",
    usage="/mascot",
    type=CommandType.LOCAL_UI,
    handler=handle_mascot,
)
