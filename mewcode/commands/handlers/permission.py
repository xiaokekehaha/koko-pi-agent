# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.permissions import PermissionMode


_MODE_NAMES = {m.value: m for m in PermissionMode}


async def handle_permission(ctx: CommandContext) -> None:
    if ctx.agent is None:
        ctx.ui.add_system_message("Agent 未初始化")
        return

    parts = ctx.args.split(None, 1)
    sub = parts[0] if parts else ""

    if sub == "":
        mode = ctx.agent.permission_mode
        checker = ctx.agent.permission_checker
        rule_count = 0
        if checker and checker.rule_engine:
            tiers = checker.rule_engine._load_tiers()
            rule_count = sum(len(t) for t in tiers)
        ctx.ui.add_system_message(
            f"权限状态\n"
            f"  当前模式: {mode.value}\n"
            f"  规则数量: {rule_count}"
        )

    elif sub == "mode":
        mode_str = parts[1].strip() if len(parts) > 1 else ""
        if not mode_str:
            modes = ", ".join(_MODE_NAMES.keys())
            ctx.ui.add_system_message(f"用法: /permission mode <模式>\n可选: {modes}")
            return
        mode = _MODE_NAMES.get(mode_str)
        if mode is None:
            modes = ", ".join(_MODE_NAMES.keys())
            ctx.ui.add_system_message(f"未知模式: {mode_str}\n可选: {modes}")
            return
        ctx.agent.set_permission_mode(mode)
        ctx.ui.refresh_status()
        ctx.ui.add_system_message(f"权限模式已切换为: {mode.value}")

    elif sub == "rules":
        checker = ctx.agent.permission_checker
        if not checker or not checker.rule_engine:
            ctx.ui.add_system_message("规则引擎未初始化")
            return
        tiers = checker.rule_engine._load_tiers()
        names = ["用户级", "项目级", "本地级"]
        lines: list[str] = ["权限规则："]
        for name, rules in zip(names, tiers):
            if rules:
                lines.append(f"  [{name}]")
                for r in rules:
                    lines.append(f"    {r.tool_name}({r.pattern}) → {r.effect}")
            else:
                lines.append(f"  [{name}] (无规则)")
        ctx.ui.add_system_message("\n".join(lines))

    elif sub == "add":
        rule_str = parts[1].strip() if len(parts) > 1 else ""
        if not rule_str:
            ctx.ui.add_system_message("用法: /permission add <规则> <效果>")
            return
        from mewcode.permissions.rules import Rule, parse_rule
        rule_parts = rule_str.rsplit(None, 1)
        if len(rule_parts) < 2 or rule_parts[1] not in ("allow", "deny"):
            ctx.ui.add_system_message(
                "用法: /permission add <Tool(pattern)> <allow|deny>\n"
                "示例: /permission add Bash(git*) allow"
            )
            return
        try:
            rule = parse_rule(rule_parts[0], rule_parts[1])
        except ValueError as e:
            ctx.ui.add_system_message(str(e))
            return
        checker = ctx.agent.permission_checker
        if checker and checker.rule_engine:
            checker.rule_engine.append_local_rule(rule)
            ctx.ui.add_system_message(f"规则已添加: {rule.tool_name}({rule.pattern}) → {rule.effect}")
        else:
            ctx.ui.add_system_message("规则引擎未初始化")


    elif sub == "reset":
        checker = ctx.agent.permission_checker
        if checker and checker.rule_engine and checker.rule_engine._local_path:
            path = checker.rule_engine._local_path
            if path.exists():
                path.write_text("", encoding="utf-8")
            ctx.ui.add_system_message("本地规则已清空")
        else:
            ctx.ui.add_system_message("无本地规则文件")

    else:
        ctx.ui.add_system_message(
            "用法: /permission [mode <模式> | rules | add <规则> <效果> | reset]"
        )


PERMISSION_COMMAND = Command(
    name="permission",
    description="权限管理",
    usage="/permission [mode <模式> | rules | add <规则> | reset]",
    type=CommandType.LOCAL,
    handler=handle_permission,
)

