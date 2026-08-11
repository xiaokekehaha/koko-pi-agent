# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_memory(ctx: CommandContext) -> None:
    mm = ctx.memory_manager
    if mm is None:
        ctx.ui.add_system_message("记忆管理器未初始化")
        return


    parts = ctx.args.split(None, 1)
    sub = parts[0] if parts else ""

    if sub == "":
        display = mm.get_display_text()
        ctx.ui.add_system_message(display)

    elif sub == "list":
        display = mm.get_display_text()
        ctx.ui.add_system_message(display)

    elif sub == "clear":
        mm.clear()
        ctx.ui.add_system_message("所有自动记忆已清空。")

    elif sub == "edit":
        ctx.ui.add_system_message(
            f"编辑记忆文件：\n"
            f"  用户级目录: {mm.user_mem_dir}\n"
            f"  项目级目录: {mm.project_mem_dir}"
        )

    else:
        ctx.ui.add_system_message(
            "用法: /memory [list | clear | edit]"
        )


MEMORY_COMMAND = Command(
    name="memory",
    description="记忆管理",
    usage="/memory [list | clear | edit]",
    type=CommandType.LOCAL,
    handler=handle_memory,
)

