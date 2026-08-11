# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from mewcode.commands.registry import Command, CommandContext, CommandRegistry, CommandType

if TYPE_CHECKING:
    from mewcode.skills.executor import SkillExecutor
    from mewcode.skills.loader import SkillLoader

log = logging.getLogger(__name__)

_REGISTERED_SKILL_NAMES: set[str] = set()


def register_skill_commands(
    registry: CommandRegistry,
    loader: SkillLoader,
    executor: SkillExecutor | None = None,
) -> None:
    for name in list(_REGISTERED_SKILL_NAMES):
        if registry.find(name) is not None:
            registry._commands.pop(name, None)
            registry._alias_map = {
                k: v for k, v in registry._alias_map.items() if v != name
            }
        _REGISTERED_SKILL_NAMES.discard(name)

    for skill_name, skill_desc in loader.get_catalog():
        if registry.find(skill_name) is not None:
            continue

        s_name = skill_name
        s_desc = skill_desc


        def make_handler(name: str) -> callable:


            async def handler(ctx: CommandContext) -> None:
                exe = ctx.config.get("skill_executor") if executor is None else executor
                if exe is None:
                    ctx.ui.add_system_message("Skill 执行器未初始化")
                    return

                skill_loader: SkillLoader | None = ctx.config.get("skill_loader")
                if skill_loader is None:
                    ctx.ui.add_system_message("Skill 加载器未初始化")
                    return

                skill = skill_loader.get(name)
                if skill is None:
                    ctx.ui.add_system_message(f"未找到 Skill：{name}")
                    return

                if skill.mode == "fork":
                    ctx.ui.add_system_message(f"⏳ Running {name} skill...")


                    async def _run_fork() -> None:
                        try:
                            result = await exe.execute_fork(skill, ctx.args)
                            ctx.ui.add_system_message(
                                f"[{name} skill result]\n{result}"
                            )
                        except Exception as e:
                            ctx.ui.add_system_message(
                                f"Skill {name} failed: {e}"
                            )

                    asyncio.create_task(_run_fork())
                else:
                    exe.execute_inline(skill, ctx.args)
                    ctx.ui.add_system_message(
                        f"skill({name})\nSuccessfully loaded skill"
                    )
                    trigger = ctx.args if ctx.args else f"/{name}"
                    ctx.ui.send_user_message(trigger)

            return handler

        cmd = Command(
            name=s_name,
            description=f"{s_desc} [skill]",
            usage=f"/{s_name} [args]",
            type=CommandType.PROMPT,
            handler=make_handler(s_name),
        )

        try:
            registry.register_sync(cmd)
            _REGISTERED_SKILL_NAMES.add(s_name)
        except ValueError as e:
            log.warning("Cannot register skill command '%s': %s", s_name, e)
