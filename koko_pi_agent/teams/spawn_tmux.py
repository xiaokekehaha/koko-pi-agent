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
class TmuxPaneInfo:
    pane_id: str
    session: str


class TmuxSpawnError(Exception):
    pass


def _run_tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise TmuxSpawnError(f"tmux {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def spawn_tmux_teammate(
    team_name: str,
    member_name: str,
    cli_command: str,
) -> TmuxPaneInfo:
    """在新的 tmux 窗口里跑起队友 worker。

    cli_command 由 build_teammate_cli 产出（cd 到工作目录后 `-m koko_pi_agent --teammate`）。
    用 new-window（而非 split 分屏）为每个队友开一个独立窗口，窗口名为 team-member。
    """
    window_name = f"{team_name}-{member_name}"

    # -d 表示不自动切到新窗口，队友在后台运行
    _run_tmux("new-window", "-d", "-n", window_name, cli_command)

    log.info("Spawned tmux teammate %s in window %s", member_name, window_name)
    return TmuxPaneInfo(pane_id=window_name, session=team_name)


def send_keys_to_pane(pane_id: str, keys: str = "") -> None:
    """向指定 tmux 窗口发送按键（用于唤醒空闲轮询中的队友）。"""
    try:
        _run_tmux("send-keys", "-t", pane_id, keys, "Enter")
    except TmuxSpawnError:
        log.warning("Failed to send keys to tmux pane %s", pane_id)


def kill_pane(pane_id: str) -> None:
    """关闭队友所在的 tmux 窗口。"""
    try:
        # 先发 Ctrl-C 让队友主循环干净退出，再关掉窗口
        _run_tmux("send-keys", "-t", pane_id, "C-c", "")
    except TmuxSpawnError:
        pass
    try:
        _run_tmux("kill-window", "-t", pane_id)
    except TmuxSpawnError:
        pass
