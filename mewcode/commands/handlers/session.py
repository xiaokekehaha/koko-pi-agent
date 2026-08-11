# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.conversation import ConversationManager


async def handle_session(ctx: CommandContext) -> None:
    sm = ctx.session_manager
    if sm is None:
        ctx.ui.add_system_message("会话管理器未初始化")
        return

    parts = ctx.args.split(None, 1)
    sub = parts[0] if parts else ""

    if sub == "":
        if ctx.session:
            m = ctx.session.meta
            ts = m.last_active.strftime("%Y-%m-%d %H:%M")
            ctx.ui.add_system_message(
                f"当前会话: {m.id}\n"
                f"  标题: {m.title or '(未命名)'}\n"
                f"  消息: {m.message_count} 条\n"
                f"  Token: {m.total_tokens:,}\n"
                f"  最后活跃: {ts}"
            )
        else:
            ctx.ui.add_system_message("当前没有活跃会话")
        return

    if sub == "list":
        metas = sm.list()
        if not metas:
            ctx.ui.add_system_message("没有已保存的会话。")
            return
        lines: list[str] = ["会话列表："]
        for m in metas[:10]:
            ts = m.last_active.strftime("%Y-%m-%d %H:%M")
            title = m.title or "(未命名)"
            lines.append(f"  {m.id}  {title}  [{m.message_count} msgs, {ts}]")
        ctx.ui.add_system_message("\n".join(lines))

    elif sub == "resume":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            metas = sm.list()
            if not metas:
                ctx.ui.add_system_message("没有已保存的会话。")
                return
            lines: list[str] = ["可恢复的会话（使用 /session resume <id> 或 /session resume <序号>）："]
            for i, m in enumerate(metas[:15], 1):
                ts = m.last_active.strftime("%Y-%m-%d %H:%M")
                title = m.title or "(未命名)"
                lines.append(f"  {i}. [{m.id[:8]}]  {title}  ({m.message_count} msgs, {ts})")
            ctx.ui.add_system_message("\n".join(lines))
            ctx.config["_resume_candidates"] = [m.id for m in metas[:15]]
            return
        candidates = ctx.config.get("_resume_candidates", [])
        if session_id.isdigit() and candidates:
            idx = int(session_id) - 1
            if 0 <= idx < len(candidates):
                session_id = candidates[idx]
        result = sm.resume(session_id)
        if result is None:
            ctx.ui.add_system_message(f"会话未找到: {session_id}")
            return
        if ctx.session:
            ctx.session.close()
        ctx.config["set_session"](result.session)
        conv = ConversationManager()
        for msg in result.messages:
            conv.history.append(msg)
        ctx.config["set_conversation"](conv)
        if ctx.agent:
            ctx.agent._loop_count = 0
        await ctx.config["render_restored"](result.messages)
        ctx.ui.add_system_message(
            f"会话已恢复: {session_id} ({result.session.meta.message_count} msgs)"
        )


    elif sub == "new":
        if ctx.session:
            ctx.session.close()
        new_session = sm.create()
        ctx.config["set_session"](new_session)
        ctx.config["set_conversation"](ConversationManager())
        if ctx.agent:
            ctx.agent._loop_count = 0
        ctx.config["clear_chat"]()
        ctx.ui.add_system_message(f"新会话已创建: {new_session.session_id}")

    elif sub == "delete":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            ctx.ui.add_system_message("用法: /session delete <id>")
            return
        if ctx.session and ctx.session.session_id == session_id:
            ctx.ui.add_system_message("不能删除当前活跃的会话。")
            return
        if sm.delete(session_id):
            ctx.ui.add_system_message(f"会话已删除: {session_id}")
        else:
            ctx.ui.add_system_message(f"会话未找到: {session_id}")


    else:
        ctx.ui.add_system_message(
            "用法: /session [list | resume <id> | new | delete <id>]"
        )


SESSION_COMMAND = Command(
    name="session",
    description="会话管理",
    usage="/session [list | resume <id> | new | delete <id>]",
    type=CommandType.LOCAL,
    handler=handle_session,
)

