# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import os
import sys

from mewcode.teams.models import BackendType


class BackendDetectionError(Exception):
    pass


def detect_backend_from_env() -> BackendType:
    """只按环境变量判断后端，抽出来便于单测（不受运行平台影响）。

    tmux 和 iTerm2 会自动给会话内的进程设上 TMUX / ITERM_SESSION_ID 环境变量，
    用户无需手动配置。只有已经身处这类会话里，才把队友放进独立窗格；
    否则一律进程内运行。
    """
    if os.environ.get("TMUX"):
        return BackendType.TMUX
    if os.environ.get("ITERM_SESSION_ID"):
        return BackendType.ITERM2
    return BackendType.IN_PROCESS


def detect_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """选择队友后端。

    优先级：
      1. 显式要求 in-process，或处于非交互（如 -p）模式 → 进程内。
      2. Windows 护栏：tmux 窗格 spawn 时用 pwsh 执行 POSIX 命令会失败，
         Windows 一律进程内。
      3. 否则按环境变量：已身处 tmux → tmux；已身处 iTerm2 → iterm2；
         都不是 → 进程内。
    """
    if teammate_mode == "in-process" or not is_interactive:
        return BackendType.IN_PROCESS
    if sys.platform == "win32":
        return BackendType.IN_PROCESS
    return detect_backend_from_env()


def detect_pane_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """检测窗格后端，只在“已身处 tmux / iTerm2 会话”时才启用窗格。

    不做“检测到系统装了 tmux 就用窗格”的探测，
    只有当前进程本身就跑在 tmux / iTerm2 会话里（有对应环境变量）时才用窗格，
    否则静默回退到进程内，而不是抛异常中断 team 创建流程。
    """
    if teammate_mode == "in-process" or not is_interactive:
        return BackendType.IN_PROCESS
    if sys.platform == "win32":
        return BackendType.IN_PROCESS
    return detect_backend_from_env()
