# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mewcode.teams.backend_detect import BackendDetectionError, detect_backend
from mewcode.teams.mailbox import Mailbox, create_message
from mewcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from mewcode.teams.progress import TeammateProgress
from mewcode.teams.registry import AgentNameRegistry
from mewcode.teams.shared_task import SharedTaskStore
from mewcode.teams.spawn_inprocess import InProcessTeammateHandle

if TYPE_CHECKING:
    from mewcode.agent import Agent

log = logging.getLogger(__name__)


class TeamError(Exception):
    pass


class TeamManager:
    def __init__(self, worktree_manager: Any = None, trace_manager: Any = None) -> None:
        self._teams: dict[str, AgentTeam] = {}
        self._task_stores: dict[str, SharedTaskStore] = {}
        self._mailboxes: dict[str, Mailbox] = {}
        self._inprocess_handles: dict[str, InProcessTeammateHandle] = {}
        self._pane_ids: dict[str, str] = {}  # agent_id -> pane_id (tmux/iterm2)
        self._detected_backend: BackendType | None = None
        self._worktree_manager = worktree_manager
        self._trace_manager = trace_manager
        self._teammate_team_map: dict[str, str] = {}  # agent_id -> team_name

    def detect_backend(
        self,
        teammate_mode: str = "",
        is_interactive: bool = True,
    ) -> BackendType:
        if self._detected_backend is None:
            self._detected_backend = detect_backend(teammate_mode, is_interactive)
        return self._detected_backend


    def create_team(
        self,
        name: str,
        lead_agent_id: str,
        description: str = "",
        teammate_mode: str = "",
        is_interactive: bool = True,
    ) -> AgentTeam:
        backend = self.detect_backend(teammate_mode, is_interactive)
        slug = unique_team_name(name)
        team_dir = resolve_team_dir(slug)
        team_dir.mkdir(parents=True, exist_ok=True)

        config_path = str(team_dir / "config.json")
        team = AgentTeam(
            name=slug,
            lead_agent_id=lead_agent_id,
            config_path=config_path,
            description=description,
        )
        team.save()

        task_store = SharedTaskStore(team_dir / "tasks.json")
        task_store.init_empty()

        mailbox_dir = team_dir / "inboxes"
        mailbox_dir.mkdir(parents=True, exist_ok=True)
        mailbox = Mailbox(mailbox_dir)

        self._teams[slug] = team
        self._task_stores[slug] = task_store
        self._mailboxes[slug] = mailbox

        log.info("Created team '%s' at %s (backend=%s)", slug, team_dir, backend.value)
        return team


    def get_team(self, name: str) -> AgentTeam | None:
        if name in self._teams:
            return self._teams[name]
        team_dir = resolve_team_dir(name)
        config_path = team_dir / "config.json"
        if config_path.exists():
            team = AgentTeam.load(str(config_path))
            self._teams[name] = team
            return team
        return None

    def get_task_store(self, team_name: str) -> SharedTaskStore | None:
        if team_name in self._task_stores:
            return self._task_stores[team_name]
        team_dir = resolve_team_dir(team_name)
        tasks_path = team_dir / "tasks.json"
        if tasks_path.exists():
            store = SharedTaskStore(tasks_path)
            self._task_stores[team_name] = store
            return store
        return None

    def get_mailbox(self, team_name: str) -> Mailbox | None:
        if team_name in self._mailboxes:
            return self._mailboxes[team_name]
        team_dir = resolve_team_dir(team_name)
        mailbox_dir = team_dir / "inboxes"
        if mailbox_dir.exists():
            mailbox = Mailbox(mailbox_dir)
            self._mailboxes[team_name] = mailbox
            return mailbox
        return None

    def register_member(
        self,
        team_name: str,
        member: TeammateInfo,
    ) -> None:
        team = self.get_team(team_name)
        if team is None:
            raise TeamError(f"Team '{team_name}' not found")
        team.add_member(member)
        team.save()

        AgentNameRegistry.instance().register(member.name, member.agent_id)
        self._teammate_team_map[member.agent_id] = team_name
        log.info("Registered member '%s' (agent=%s) in team '%s'", member.name, member.agent_id, team_name)

    def set_member_idle(self, team_name: str, member_name: str) -> None:
        team = self.get_team(team_name)
        if team is None:
            return
        team.set_member_active(member_name, False)
        team.save()

        mailbox = self.get_mailbox(team_name)
        if mailbox:
            msg = create_message(
                from_agent=member_name,
                text=f"Teammate '{member_name}' is now idle (run_to_completion finished).",
            )
            mailbox.write(team.lead_agent_id, msg)

    def register_inprocess_handle(self, agent_id: str, handle: InProcessTeammateHandle) -> None:
        self._inprocess_handles[agent_id] = handle

    def register_pane_id(self, agent_id: str, pane_id: str) -> None:
        self._pane_ids[agent_id] = pane_id


    def get_pane_id(self, agent_id: str) -> str | None:
        return self._pane_ids.get(agent_id)


    def stop_member(self, name: str) -> tuple[str, bool] | None:
        """按队员名中止一个在跑的队员，返回 (团队名, 是否真的停下了一个)。

        队员按后端分两条路生出来：in-process 的挂在 _inprocess_handles 上，
        tmux / iTerm2 的是独立进程，句柄是 _pane_ids 里的窗格号。
        两条都要覆盖，只认其中一条就会漏掉另一种后端派出去的队员。
        找不到该队员时返回 None。
        """
        for team_name in self.list_teams():
            team = self.get_team(team_name)
            if team is None:
                continue
            member = team.get_member(name)
            if member is None:
                continue

            stopped = False

            handle = self._inprocess_handles.get(member.agent_id)
            if handle is not None and not handle.done:
                handle.cancel()
                self._inprocess_handles.pop(member.agent_id, None)
                stopped = True

            pane_id = self._pane_ids.get(member.agent_id)
            if pane_id:
                self._kill_pane(pane_id, member.backend_type)
                self._pane_ids.pop(member.agent_id, None)
                stopped = True

            if stopped:
                member.is_active = False
            return team_name, stopped

        return None


    def delete_team(self, team_name: str) -> None:
        team = self.get_team(team_name)
        if team is None:
            raise TeamError(f"Team '{team_name}' not found")

        active = [m for m in team.members if m.is_active is not False]
        if active:
            names = ", ".join(m.name for m in active)
            raise TeamError(f"Cannot delete team: active members: {names}")

        for member in list(team.members):
            AgentNameRegistry.instance().unregister(member.name)

            handle = self._inprocess_handles.pop(member.agent_id, None)
            if handle and not handle.done:
                handle.cancel()

            pane_id = self._pane_ids.pop(member.agent_id, None)
            if pane_id:
                self._kill_pane(pane_id, member.backend_type)

            if member.worktree_path:
                self._cleanup_worktree(member.worktree_path)

            if self._trace_manager:
                self._trace_manager.remove(member.agent_id)

        mailbox = self.get_mailbox(team_name)
        if mailbox:
            mailbox.cleanup_all()

        team_dir = resolve_team_dir(team_name)
        self._remove_dir(team_dir)

        self._teams.pop(team_name, None)
        self._task_stores.pop(team_name, None)
        self._mailboxes.pop(team_name, None)

        log.info("Deleted team '%s'", team_name)

    def list_teams(self) -> list[str]:
        return list(self._teams.keys())

    def get_team_for_teammate(self, agent_id: str) -> str | None:
        if agent_id in self._teammate_team_map:
            return self._teammate_team_map[agent_id]
        for name, team in self._teams.items():
            for m in team.members:
                if m.agent_id == agent_id:
                    return name
        return None


    def drain_lead_mailbox(self) -> list[str]:
        notes: list[str] = []
        for team_name in list(self._teams.keys()):
            team = self.get_team(team_name)
            if team is None:
                continue
            mailbox = self.get_mailbox(team_name)
            if mailbox is None:
                continue
            msgs = mailbox.consume(team.lead_agent_id)
            if not msgs:
                continue
            parts = [f'<team-notification team="{team_name}">']
            for m in msgs:
                parts.append(f"from={m.from_agent}: {m.text}")
            parts.append("</team-notification>")
            notes.append("\n".join(parts))
        return notes

    def get_all_teammate_progress(self) -> list[TeammateProgress]:
        """Collect progress objects attached to every registered teammate."""
        results: list[TeammateProgress] = []
        for team in self._teams.values():
            for member in team.members:
                if hasattr(member, "progress") and member.progress is not None:
                    results.append(member.progress)
        return results

    def on_teammate_completed(self, agent_id: str) -> None:
        team_name = self.get_team_for_teammate(agent_id)
        if team_name is None:
            return
        team = self.get_team(team_name)
        if team is None:
            return
        member = next((m for m in team.members if m.agent_id == agent_id), None)
        if member:
            self.set_member_idle(team_name, member.name)


    def _kill_pane(self, pane_id: str, backend_type: str) -> None:
        try:
            if backend_type == BackendType.TMUX.value:
                from mewcode.teams.spawn_tmux import kill_pane
                kill_pane(pane_id)
            elif backend_type == BackendType.ITERM2.value:
                from mewcode.teams.spawn_iterm2 import kill_pane
                kill_pane(pane_id)
        except Exception as e:
            log.warning("Failed to kill pane %s: %s", pane_id, e)

    def _cleanup_worktree(self, worktree_path: str) -> None:
        import subprocess
        try:
            subprocess.run(
                ["git", "worktree", "remove", worktree_path, "--force"],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            log.warning("git worktree remove failed for %s: %s", worktree_path, e)
            import shutil
            try:
                if Path(worktree_path).exists():
                    shutil.rmtree(worktree_path, ignore_errors=True)
            except Exception:
                pass

    def _remove_dir(self, path: Path) -> None:
        import shutil
        try:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        except Exception as e:
            log.warning("Failed to remove directory %s: %s", path, e)
