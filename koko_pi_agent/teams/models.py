# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
import os
import time
from pathlib import Path
from typing import Optional

from koko_pi_agent.teams.progress import TeammateProgress


class BackendType(str, Enum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str
    model: str
    worktree_path: str
    backend_type: str  # BackendType value
    is_active: bool | None = None
    joined_at: int = 0
    progress: Optional[TeammateProgress] = None

    def to_dict(self) -> dict:
        # config.json 里的键名一律用驼峰。
        # progress 是运行时字段（内含 threading.Lock），不落盘。
        return {
            "agentId": self.agent_id,
            "name": self.name,
            "agentType": self.agent_type,
            "model": self.model,
            "joinedAt": self.joined_at,
            "worktreePath": self.worktree_path,
            "backendType": self.backend_type,
            "isActive": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TeammateInfo:
        return cls(
            name=data.get("name", ""),
            agent_id=data.get("agentId", ""),
            agent_type=data.get("agentType", ""),
            model=data.get("model", ""),
            worktree_path=data.get("worktreePath", ""),
            backend_type=data.get("backendType", ""),
            is_active=data.get("isActive"),
            joined_at=data.get("joinedAt", 0),
        )


def _sanitize_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "team"


@dataclass
class AgentTeam:
    name: str
    lead_agent_id: str
    members: list[TeammateInfo] = field(default_factory=list)
    # config_path 是运行时算出来的落盘位置，不写进 config.json：
    # 它能由团队名推出来，存进去反而会在文件被复制或主目录变动后失效。
    config_path: str = ""
    description: str = ""
    created_at: int = 0

    def get_member(self, name: str) -> TeammateInfo | None:
        for m in self.members:
            if m.name == name or m.agent_id == name:
                return m
        return None


    def add_member(self, member: TeammateInfo) -> None:
        self.members.append(member)

    def remove_member(self, name: str) -> bool:
        for i, m in enumerate(self.members):
            if m.name == name or m.agent_id == name:
                self.members.pop(i)
                return True
        return False


    def set_member_active(self, name: str, is_active: bool | None) -> bool:
        member = self.get_member(name)
        if member is None:
            return False
        member.is_active = is_active
        return True

    def all_idle(self) -> bool:
        return all(m.is_active is False for m in self.members)


    def active_members(self) -> list[TeammateInfo]:
        return [m for m in self.members if m.is_active is not False]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "createdAt": self.created_at or int(time.time()),
            "leadAgentId": self.lead_agent_id,
            "members": [m.to_dict() for m in self.members],
        }


    @classmethod
    def from_dict(cls, data: dict) -> AgentTeam:
        members = [TeammateInfo.from_dict(m) for m in data.get("members", [])]
        return cls(
            name=data["name"],
            lead_agent_id=data.get("leadAgentId", ""),
            members=members,
            description=data.get("description", ""),
            created_at=data.get("createdAt", 0),
        )

    def save(self) -> None:
        if not self.created_at:
            self.created_at = int(time.time())
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, config_path: str) -> AgentTeam:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        team = cls.from_dict(data)
        team.config_path = config_path
        return team


def teams_base_dir() -> Path:
    """所有团队目录的根。

    放在用户主目录而不是项目目录下，因为窗格队员是独立进程、工作目录可能被
    worktree 换掉，用主目录才能保证队员进程和 Lead 找到同一份团队配置。
    """
    return Path.home() / ".koko" / "teams"


def resolve_team_dir(team_name: str) -> Path:
    slug = _sanitize_name(team_name)
    return teams_base_dir() / slug


def unique_team_name(team_name: str) -> str:
    slug = _sanitize_name(team_name)
    base_dir = teams_base_dir()
    if not (base_dir / slug).exists():
        return slug
    counter = 2
    while (base_dir / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"
