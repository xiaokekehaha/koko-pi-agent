# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


REVIEW_PROMPT = (
    "请审查当前 git diff 中的代码变更。重点关注：\n"
    "1. 逻辑错误\n"
    "2. 安全问题\n"
    "3. 性能问题\n"
    "4. 代码风格"
)


async def handle_review(ctx: CommandContext) -> None:
    prompt = REVIEW_PROMPT
    if ctx.args:
        prompt += f"\n\n额外关注：{ctx.args}"
    ctx.ui.send_user_message(prompt)


REVIEW_COMMAND = Command(
    name="review",
    description="审查代码变更",
    usage="/review [额外关注点]",
    type=CommandType.PROMPT,
    handler=handle_review,
)

