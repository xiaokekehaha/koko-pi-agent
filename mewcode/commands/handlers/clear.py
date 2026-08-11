# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.conversation import ConversationManager


async def handle_clear(ctx: CommandContext) -> None:
    if ctx.session:
        ctx.session.close()

    if ctx.session_manager:
        new_session = ctx.session_manager.create()
        ctx.config["set_session"](new_session)

        # 用新 session ID 重建 file history
        if ctx.agent:
            from mewcode.filehistory import FileHistory
            file_history = FileHistory(ctx.agent._work_dir, new_session.session_id)
            ctx.agent.file_history = file_history
            for tool in ctx.agent.registry.list_tools():
                if hasattr(tool, "file_history"):
                    tool.file_history = file_history

    ctx.config["set_conversation"](ConversationManager())

    if ctx.agent:
        ctx.agent._loop_count = 0
        ctx.agent.clear_active_skills()
        # 重置 token 计数
        ctx.agent.total_input_tokens = 0
        ctx.agent.total_output_tokens = 0

    ctx.config["clear_chat"]()
    ctx.ui.refresh_status()
    ctx.ui.add_system_message("对话已清除，新会话已创建")


CLEAR_COMMAND = Command(
    name="clear",
    description="清除对话历史",
    usage="/clear",
    type=CommandType.LOCAL_UI,
    handler=handle_clear,
)

