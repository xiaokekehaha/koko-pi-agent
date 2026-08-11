# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


def _format_aliases(cmd: Command) -> str:
    if not cmd.aliases:
        return cmd.name
    return cmd.name + ", " + ", ".join(f"/{a}" for a in cmd.aliases)


async def handle_help(ctx: CommandContext) -> None:
    registry = ctx.config["registry"]

    if ctx.args:
        cmd = registry.find(ctx.args.lower())
        if cmd is None:
            ctx.ui.add_system_message(f"未知命令：{ctx.args}，输入 /help 查看可用命令")
            return
        lines = [f"/{cmd.name}"]
        if cmd.aliases:
            lines[0] += f"  (别名: {', '.join('/' + a for a in cmd.aliases)})"
        lines.append(f"  {cmd.description}")
        if cmd.usage:
            lines.append(f"  用法: {cmd.usage}")
        if cmd.arg_prompt:
            lines.append(f"  参数: {cmd.arg_prompt}")
        ctx.ui.add_system_message("\n".join(lines))
        return

    commands = registry.list_commands()
    lines = ["可用命令："]
    for cmd in commands:
        aliases_str = f"/{_format_aliases(cmd)}"
        lines.append(f"  {aliases_str:<24} {cmd.description}")
    lines.append("")
    lines.append("输入 /help <命令名> 查看详细用法。")
    ctx.ui.add_system_message("\n".join(lines))


HELP_COMMAND = Command(
    name="help",
    aliases=["h", "?"],
    description="显示帮助信息",
    usage="/help [命令名]",
    type=CommandType.LOCAL,
    handler=handle_help,
)

