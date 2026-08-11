# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mewcode.commands.registry import Command, CommandContext, CommandType

if TYPE_CHECKING:
    from mewcode.agents.task_manager import TaskManager


def _format_elapsed(start: float, end: float | None) -> str:
    elapsed = (end or time.monotonic()) - start
    if elapsed >= 60:
        return f"{elapsed / 60:.1f}m"
    return f"{elapsed:.0f}s"


def _format_status(status: str) -> str:
    icons = {"running": "⏳", "completed": "✓", "failed": "✗", "cancelled": "⊘"}
    return f"{icons.get(status, '?')} {status}"


def create_tasks_handler(task_manager: TaskManager):


    async def handler(ctx: CommandContext) -> None:
        args = ctx.args.strip()
        parts = args.split(maxsplit=1) if args else []
        subcmd = parts[0] if parts else ""

        if subcmd == "info":
            if len(parts) < 2:
                ctx.ui.add_system_message("用法: /tasks info <task-id>")
                return
            task_id = parts[1].strip()
            bg = task_manager.get(task_id)
            if bg is None:
                ctx.ui.add_system_message(f"未找到任务: {task_id}")
                return
            elapsed = _format_elapsed(bg.start_time, bg.end_time)
            lines = [
                f"任务详情: {task_id}",
                f"  名称:    {bg.name}",
                f"  状态:    {_format_status(bg.status)}",
                f"  耗时:    {elapsed}",
                f"  Tokens:  ↑{bg.progress.input_tokens} ↓{bg.progress.output_tokens}",
            ]
            if bg.result:
                result_preview = bg.result[:2000]
                if len(bg.result) > 2000:
                    result_preview += "\n... (truncated)"
                lines.append(f"  结果:\n{result_preview}")
            ctx.ui.add_system_message("\n".join(lines))
            return

        if subcmd == "cancel":
            if len(parts) < 2:
                ctx.ui.add_system_message("用法: /tasks cancel <task-id>")
                return
            task_id = parts[1].strip()
            if task_manager.cancel(task_id):
                ctx.ui.add_system_message(f"已取消任务: {task_id}")
            else:
                ctx.ui.add_system_message(
                    f"无法取消任务: {task_id}（可能不存在或已完成）"
                )
            return

        # 默认：列出所有任务
        tasks = task_manager.list_tasks()
        if not tasks:
            ctx.ui.add_system_message("没有后台任务")
            return

        lines = ["后台任务列表:"]
        for bg in tasks:
            elapsed = _format_elapsed(bg.start_time, bg.end_time)
            lines.append(
                f"  [{bg.id}] {bg.name:<20} {_format_status(bg.status):<14} {elapsed}"
            )
        ctx.ui.add_system_message("\n".join(lines))

    return handler


def create_tasks_command(task_manager: TaskManager) -> Command:
    return Command(
        name="tasks",
        description="管理后台任务（/tasks, /tasks info <id>, /tasks cancel <id>）",
        type=CommandType.LOCAL,
        handler=create_tasks_handler(task_manager),
        aliases=["task"],
        usage="/tasks [info|cancel] [task-id]",
    )
