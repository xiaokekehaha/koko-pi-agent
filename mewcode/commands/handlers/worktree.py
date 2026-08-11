# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.commands.registry import Command, CommandContext, CommandType

if TYPE_CHECKING:
    from mewcode.worktree.manager import WorktreeManager


def create_worktree_command(manager: WorktreeManager) -> Command:


    async def handle_worktree(ctx: CommandContext) -> None:
        args = ctx.args.strip()
        if not args:
            ctx.ui.add_system_message(
                "用法:\n"
                "  /worktree create <name> [base-branch]\n"
                "  /worktree list\n"
                "  /worktree enter <name>\n"
                "  /worktree exit [--remove] [--discard]\n"
                "  /worktree status"
            )
            return

        parts = args.split()
        sub = parts[0]
        rest = parts[1:]

        if sub == "create":
            await _handle_create(ctx, manager, rest)
        elif sub == "list":
            _handle_list(ctx, manager)
        elif sub == "enter":
            await _handle_enter(ctx, manager, rest)
        elif sub == "exit":
            await _handle_exit(ctx, manager, rest)
        elif sub == "status":
            _handle_status(ctx, manager)
        else:
            ctx.ui.add_system_message(f"未知子命令: {sub}")

    return Command(
        name="worktree",
        aliases=["wt"],
        description="管理 Git Worktree",
        usage="/worktree <create|list|enter|exit|status>",
        type=CommandType.LOCAL,
        handler=handle_worktree,
    )


async def _handle_create(
    ctx: CommandContext,
    manager: WorktreeManager,
    args: list[str],
) -> None:
    if not args:
        ctx.ui.add_system_message("用法: /worktree create <name> [base-branch]")
        return

    name = args[0]
    base_branch = args[1] if len(args) > 1 else "HEAD"

    try:
        wt = await manager.create(name, base_branch)
    except Exception as e:
        ctx.ui.add_system_message(f"创建 worktree 失败: {e}")
        return

    try:
        session = await manager.enter(name)
        if ctx.agent:
            ctx.agent.work_dir = wt.path
    except Exception as e:
        ctx.ui.add_system_message(
            f"Worktree 已创建但进入失败: {e}\n路径: {wt.path}"
        )
        return

    ctx.ui.add_system_message(
        f"已创建并进入 worktree: {name}\n"
        f"路径: {wt.path}\n"
        f"分支: {wt.branch}\n"
        f"基于: {base_branch}"
    )


def _handle_list(ctx: CommandContext, manager: WorktreeManager) -> None:
    worktrees = manager.list_worktrees()
    if not worktrees:
        ctx.ui.add_system_message("当前没有活跃的 worktree")
        return

    current = manager.current_session
    lines = ["活跃的 Worktrees:", "─────────────────"]
    for wt in worktrees:
        marker = " ← 当前" if current and current.worktree_name == wt.name else ""
        lines.append(
            f"  {wt.name}{marker}\n"
            f"    路径: {wt.path}\n"
            f"    分支: {wt.branch}\n"
            f"    创建: {wt.created.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    ctx.ui.add_system_message("\n".join(lines))


async def _handle_enter(
    ctx: CommandContext,
    manager: WorktreeManager,
    args: list[str],
) -> None:
    if not args:
        ctx.ui.add_system_message("用法: /worktree enter <name>")
        return

    name = args[0]
    try:
        session = await manager.enter(name)
        if ctx.agent:
            ctx.agent.work_dir = session.worktree_path
        ctx.ui.add_system_message(f"已进入 worktree: {name}\n路径: {session.worktree_path}")
    except Exception as e:
        ctx.ui.add_system_message(f"进入 worktree 失败: {e}")


async def _handle_exit(
    ctx: CommandContext,
    manager: WorktreeManager,
    args: list[str],
) -> None:
    session = manager.get_current_session()
    if session is None:
        ctx.ui.add_system_message("当前不在任何 worktree 中")
        return

    remove = "--remove" in args
    discard = "--discard" in args
    action = "remove" if remove else "keep"

    try:
        await manager.exit(session.worktree_name, action=action, discard_changes=discard)
        if ctx.agent:
            ctx.agent.work_dir = session.original_cwd
        msg = f"已退出 worktree: {session.worktree_name}"
        if remove:
            msg += "（已删除）"
        ctx.ui.add_system_message(msg)
    except Exception as e:
        ctx.ui.add_system_message(f"退出 worktree 失败: {e}")


def _handle_status(ctx: CommandContext, manager: WorktreeManager) -> None:
    session = manager.get_current_session()
    if session is None:
        ctx.ui.add_system_message("当前不在任何 worktree 中")
        return

    lines = [
        "Worktree 会话状态:",
        "──────────────────",
        f"  名称: {session.worktree_name}",
        f"  路径: {session.worktree_path}",
        f"  原始目录: {session.original_cwd}",
        f"  原始分支: {session.original_branch}",
    ]
    ctx.ui.add_system_message("\n".join(lines))
