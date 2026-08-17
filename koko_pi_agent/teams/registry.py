# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import threading


class AgentNameRegistry:
    _instance: AgentNameRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._names: dict[str, str] = {}  # name -> agent_id


    @classmethod
    def instance(cls) -> AgentNameRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None


    def register(self, name: str, agent_id: str) -> None:
        self._names[name] = agent_id

    def resolve(self, name_or_id: str) -> str | None:
        if name_or_id in self._names:
            return self._names[name_or_id]
        if name_or_id in self._names.values():
            return name_or_id
        return None

    def unregister(self, name: str) -> None:
        self._names.pop(name, None)
