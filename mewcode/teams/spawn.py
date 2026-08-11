# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import os
import sys


def shell_quote(s: str) -> str:
    """把一个值包成可安全放进 /bin/sh -c 参数里的单引号字符串。

    tmux send-keys 和 osascript 的 write text 都会把字符串再交给 shell 解析，
    因此这里用单引号转义：空串给 ''；不含特殊字符的原样返回；否则包单引号，
    内部的单引号替换成 '\\''。
    """
    if s == "":
        return "''"
    if not any(c in s for c in " \t\n'\"\\$`"):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def build_teammate_cli(team_name: str, member_name: str, workdir: str = "") -> str:
    """构造在新终端窗格/标签里把本进程拉起为“队友 worker 模式”的 shell 命令。

    用 sys.executable + `-m mewcode` 复用当前
    Python 解释器和包，产出形如：

        cd <workdir> && <python> -m mewcode --teammate --team-name <t> --agent-name <n>

    workdir 控制 spawn 出来的进程在哪个目录运行；传空则回退到 lead 的当前目录，
    这样邮箱路径能解析成同一个位置（worktree 隔离时传非空的 worktree 路径）。
    输出格式与 __main__.py 里解析 --teammate 的分支一一对应。
    """
    if not workdir:
        workdir = os.getcwd()
    python = sys.executable or "python"
    return (
        f"cd {shell_quote(workdir)} && "
        f"{shell_quote(python)} -m mewcode --teammate "
        f"--team-name {shell_quote(team_name)} "
        f"--agent-name {shell_quote(member_name)}"
    )
