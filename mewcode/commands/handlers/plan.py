# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.prompts import build_plan_mode_reentry_reminder


async def handle_plan(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(True)
    ctx.ui.add_system_message("已切换到 Plan 模式 — 只读，禁止写入和命令执行")

    # 重入检测：如果本次会话曾退出过 Plan Mode 且 plan 文件已存在，注入重入提示
    app = ctx.ui
    if getattr(app, "_has_exited_plan_mode", False) and ctx.agent is not None:
        plan_path = ctx.agent._get_plan_path()
        plan_exists = plan_path.exists()
        reentry_msg = build_plan_mode_reentry_reminder(str(plan_path), plan_exists)
        if reentry_msg:
            ctx.ui.add_system_message(reentry_msg)
            app._has_exited_plan_mode = False

    if ctx.args:
        ctx.ui.send_user_message(ctx.args)


PLAN_COMMAND = Command(
    name="plan",
    aliases=["p"],
    description="切换到 Plan 模式",
    usage="/plan [任务描述]",
    type=CommandType.LOCAL_UI,
    handler=handle_plan,
)

