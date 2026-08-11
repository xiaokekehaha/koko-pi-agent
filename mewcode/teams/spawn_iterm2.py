# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ITermPaneInfo:
    session_id: str


class ITermSpawnError(Exception):
    pass


def spawn_iterm2_teammate(
    team_name: str,
    member_name: str,
    cli_command: str,
) -> ITermPaneInfo:
    """在新的 iTerm2 标签页里跑起队友 worker。

    通过 AppleScript（osascript）新建一个标签页并在其中执行 cli_command。
    返回脚本侧的标签标识（team-member），供后续关闭时定位。仅 macOS 可用。
    """
    tab_name = f"{team_name}-{member_name}"
    # 转义内嵌的双引号，保证 AppleScript 字符串字面量合法
    safe_cmd = cli_command.replace('"', '\\"')
    safe_name = tab_name.replace('"', '\\"')
    script = (
        'tell application "iTerm2"\n'
        "  tell current window\n"
        "    set newTab to create tab with default profile\n"
        "    tell newTab\n"
        f'      set name to "{safe_name}"\n'
        "      tell current session\n"
        f'        write text "{safe_cmd}"\n'
        "      end tell\n"
        "    end tell\n"
        "  end tell\n"
        "end tell"
    )

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ITermSpawnError(
            f"osascript failed for {member_name}: {result.stderr.strip()}"
        )

    log.info("Spawned iTerm2 teammate %s in tab %s", member_name, tab_name)
    return ITermPaneInfo(session_id=tab_name)


def kill_pane(tab_name: str) -> None:
    """关闭队友所在的 iTerm2 标签页。尽力而为。"""
    safe_name = tab_name.replace('"', '\\"')
    script = (
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        f'      if name of t is "{safe_name}" then\n'
        "        tell t to close\n"
        "      end if\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell"
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception:
        pass
