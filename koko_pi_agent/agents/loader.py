# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from koko_pi_agent.agents.builtins import BUILTIN_AGENT_FILES
from koko_pi_agent.agents.parser import (
    AgentDef,
    AgentParseError,
    _validate_agent_meta,
    parse_agent_file,
    parse_frontmatter,
)

log = logging.getLogger(__name__)

PROJECT_AGENTS_DIR = ".koko/agents"
USER_AGENTS_DIR = "~/.koko/agents"

BUILTINS_PACKAGE = "koko_pi_agent.agents.builtins"


class BuiltinAgentError(RuntimeError):
    """内置 agent 定义缺失或损坏。

    这一层是随包分发的，出问题只可能是打包错误或误删，不是用户输入问题，
    所以直接抛出而不是降级成空列表——静默降级会让 Explore/Plan/Verification
    等内建类型悄悄消失，而调用方（AgentTool、团队协调 prompt）仍在引用它们。
    """


class AgentLoader:


    def __init__(
        self,
        work_dir: str,
        enable_verification: bool = False,
    ) -> None:
        self._work_dir = work_dir
        self._enable_verification = enable_verification
        self._agents: dict[str, AgentDef] = {}


    def _scan_directory(self, path: Path, source: str) -> list[AgentDef]:
        results: list[AgentDef] = []
        if not path.is_dir():
            return results

        for entry in sorted(path.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            try:
                agent_def = parse_agent_file(entry)
                agent_def.source = source
                agent_def.file_path = entry
                results.append(agent_def)
            except AgentParseError as e:
                log.warning("Skipping agent file %s: %s", entry, e)
        return results


    def _load_builtins(self) -> list[AgentDef]:
        """按 BUILTIN_AGENT_FILES 清单加载内置 agent。

        不遍历目录而是照清单取文件：目录里少了什么，这里才能发现。
        """
        try:
            builtins_pkg = importlib.resources.files(BUILTINS_PACKAGE)
        except (ModuleNotFoundError, TypeError) as e:
            raise BuiltinAgentError(
                f"内置 agent 包 {BUILTINS_PACKAGE} 无法加载，安装不完整"
            ) from e

        results: list[AgentDef] = []
        for filename in BUILTIN_AGENT_FILES:
            item = builtins_pkg / filename
            if not item.is_file():
                raise BuiltinAgentError(
                    f"内置 agent 定义 {filename} 缺失。它在 "
                    f"{BUILTINS_PACKAGE}.BUILTIN_AGENT_FILES 中声明——"
                    f"要么恢复该文件，要么把它从清单里移除。"
                )

            try:
                meta, body = parse_frontmatter(item.read_text(encoding="utf-8"))
                _validate_agent_meta(meta, filename)
            except (AgentParseError, OSError) as e:
                raise BuiltinAgentError(f"内置 agent {filename} 无效：{e}") from e

            agent_def = AgentDef(
                agent_type=meta["name"],
                when_to_use=meta["description"],
                system_prompt=body,
                tools=meta.get("tools", []),
                disallowed_tools=meta.get("disallowedTools", []),
                model=str(meta.get("model", "inherit")),
                max_turns=meta.get("maxTurns") or 200,  # 未指定时默认 200
                permission_mode=str(meta.get("permissionMode", "default")),
                background=bool(meta.get("background", False)),
                isolation=str(meta.get("isolation", "")),
                # 内置定义随包分发，不参与 get() 的热重载
                file_path=None,
                source="builtin",
            )

            if (
                agent_def.agent_type == "Verification"
                and not self._enable_verification
            ):
                continue

            results.append(agent_def)

        return results

    def load_all(self) -> dict[str, AgentDef]:
        seen: dict[str, AgentDef] = {}

        # 优先级 1：项目级（最高）
        project_path = Path(self._work_dir) / PROJECT_AGENTS_DIR
        for agent_def in self._scan_directory(project_path, "project"):
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 2：用户级
        user_path = Path(USER_AGENTS_DIR).expanduser()
        for agent_def in self._scan_directory(user_path, "user"):
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 3：内置
        for agent_def in self._load_builtins():
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 4：插件（保留，未实现）

        self._agents = seen
        return seen


    def get(self, agent_type: str) -> AgentDef | None:
        cached = self._agents.get(agent_type)
        if cached is None:
            return None

        # 从文件热重载
        if cached.file_path is not None and cached.file_path.exists():
            try:
                reloaded = parse_agent_file(cached.file_path)
                reloaded.source = cached.source
                self._agents[agent_type] = reloaded
                return reloaded
            except AgentParseError as e:
                log.warning(
                    "Hot reload failed for %s, using cached: %s",
                    agent_type,
                    e,
                )
        return cached


    def list_agents(self) -> list[tuple[str, str]]:
        return [
            (ad.agent_type, ad.when_to_use) for ad in self._agents.values()
        ]

    def register_plugin_source(self, path: Path) -> None:
        pass
