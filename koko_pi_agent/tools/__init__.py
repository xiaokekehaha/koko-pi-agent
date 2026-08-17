# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from koko_pi_agent.tools.base import Tool


@dataclass(frozen=True)
class ContributionOwner:
    extension_id: str
    source: str
    runtime_id: str = ""
    generation: int = 0
    borrowed_from: str | None = None


@dataclass(frozen=True)
class ToolContribution:
    name: str
    tool: Tool
    owner: ContributionOwner
    sequence: int
    _token: object = field(repr=False, compare=False)


_LEGACY_OWNER = ContributionOwner(extension_id="legacy", source="legacy")


class ToolConflictError(ValueError):
    def __init__(
        self,
        name: str,
        existing: ToolContribution,
        attempted_owner: ContributionOwner,
    ) -> None:
        self.name = name
        self.existing = existing
        self.attempted_owner = attempted_owner
        super().__init__(
            f"Tool '{name}' is already registered by "
            f"{existing.owner.extension_id} ({existing.owner.source}); attempted by "
            f"{attempted_owner.extension_id} ({attempted_owner.source})"
        )


class RegistrationHandle:
    def __init__(self, registry: ToolRegistry, name: str, token: object) -> None:
        self._registry = registry
        self._name = name
        self._token = token
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._registry._unregister(self._name, self._token)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolContribution] = {}
        self._disabled: set[str] = set()
        self._discovered: set[str] = set()
        self._next_sequence = 1

    def register(
        self,
        tool: Tool,
        *,
        owner: ContributionOwner | None = None,
    ) -> RegistrationHandle:
        contribution_owner = owner or _LEGACY_OWNER
        existing = self._tools.get(tool.name)
        if existing is not None:
            raise ToolConflictError(tool.name, existing, contribution_owner)
        token = object()
        contribution = ToolContribution(
            name=tool.name,
            tool=tool,
            owner=contribution_owner,
            sequence=self._next_sequence,
            _token=token,
        )
        self._next_sequence += 1
        self._tools[tool.name] = contribution
        return RegistrationHandle(self, tool.name, token)

    def _unregister(self, name: str, token: object) -> None:
        contribution = self._tools.get(name)
        if contribution is None or contribution._token is not token:
            return
        del self._tools[name]
        self._disabled.discard(name)
        self._discovered.discard(name)

    def get(self, name: str) -> Tool | None:
        contribution = self._tools.get(name)
        return contribution.tool if contribution is not None else None

    def list_contributions(self) -> tuple[ToolContribution, ...]:
        return tuple(self._tools.values())

    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    def enable(self, name: str) -> None:
        self._disabled.discard(name)

    def disable(self, name: str) -> None:
        if name in self._tools:
            self._disabled.add(name)

    def enable_all(self) -> None:
        self._disabled.clear()

    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name, contribution in self._tools.items()
            if getattr(contribution.tool, "should_defer", False)
            and name not in self._discovered
            and name not in self._disabled
        ]

    def search_deferred(
        self, query: str, max_results: int, protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[int, str, Tool]] = []
        for name, contribution in self._tools.items():
            tool = contribution.tool
            if not getattr(tool, "should_defer", False):
                continue
            if name in self._disabled:
                continue
            score = 0
            name_lower = name.lower()
            desc_lower = (tool.description or "").lower()
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5
            for word in query_lower.split():
                if word in name_lower:
                    score += 3
                if word in desc_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for _, _name, tool in scored[:max_results]:
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append(
                    {
                        "type": "function",
                        "name": base["name"],
                        "description": base["description"],
                        "parameters": base["input_schema"],
                    }
                )
            else:
                results.append(base)
        return results

    def find_deferred_by_names(
        self, names: list[str], protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for name in names:
            contribution = self._tools.get(name)
            if contribution is None:
                continue
            tool = contribution.tool
            if not getattr(tool, "should_defer", False):
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append(
                    {
                        "type": "function",
                        "name": base["name"],
                        "description": base["description"],
                        "parameters": base["input_schema"],
                    }
                )
            else:
                results.append(base)
        return results

    def list_tools(self) -> list[Tool]:
        return [contribution.tool for contribution in self._tools.values()]

    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name, contribution in self._tools.items():
            tool = contribution.tool
            if name in self._disabled:
                continue
            if getattr(tool, "should_defer", False) and name not in self._discovered:
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                schemas.append(
                    {
                        "type": "function",
                        "name": base["name"],
                        "description": base["description"],
                        "parameters": base["input_schema"],
                    }
                )
            else:
                schemas.append(base)
        return schemas


class ToolView(ToolRegistry):
    def __init__(
        self,
        parent: ToolRegistry,
        *,
        names: Iterable[str] | None = None,
        replacements: Mapping[str, Tool] | None = None,
        additions: Iterable[Tool] = (),
        local_owner: ContributionOwner | None = None,
    ) -> None:
        super().__init__()
        self._parent = parent
        self._view_handles: list[RegistrationHandle] = []
        self._state = "active"
        replacement_tools = replacements or {}
        try:
            parent_contributions = parent.list_contributions()
            if names is None:
                selected_contributions = parent_contributions
            else:
                by_name = {
                    contribution.name: contribution
                    for contribution in parent_contributions
                }
                selected_contributions = tuple(
                    by_name[name] for name in names if name in by_name
                )
            for contribution in selected_contributions:
                origin = (
                    contribution.owner.borrowed_from
                    or contribution.owner.runtime_id
                    or contribution.owner.extension_id
                )
                owner = ContributionOwner(
                    extension_id=contribution.owner.extension_id,
                    source=contribution.owner.source,
                    generation=contribution.owner.generation,
                    borrowed_from=origin,
                )
                tool = replacement_tools.get(contribution.name, contribution.tool)
                self._view_handles.append(
                    ToolRegistry.register(self, tool, owner=owner)
                )
            addition_owner = local_owner or ContributionOwner(
                extension_id="koko_pi_agent.tool-view-local",
                source="runtime-local",
            )
            for tool in additions:
                self._view_handles.append(
                    ToolRegistry.register(self, tool, owner=addition_owner)
                )
        except BaseException:
            self.close()
            raise

    @classmethod
    def borrow(
        cls,
        parent: ToolRegistry,
        *,
        names: Iterable[str] | None = None,
        replacements: Mapping[str, Tool] | None = None,
        additions: Iterable[Tool] = (),
        local_owner: ContributionOwner | None = None,
    ) -> ToolView:
        return cls(
            parent,
            names=names,
            replacements=replacements,
            additions=additions,
            local_owner=local_owner,
        )

    @property
    def parent(self) -> ToolRegistry:
        return self._parent

    @property
    def state(self) -> str:
        return self._state

    def register(
        self,
        tool: Tool,
        *,
        owner: ContributionOwner | None = None,
    ) -> RegistrationHandle:
        raise RuntimeError("ToolView is read-only")

    def close(self) -> None:
        if self._state == "closed":
            return
        for handle in reversed(self._view_handles):
            handle.close()
        self._view_handles.clear()
        self._state = "closed"


def create_default_registry(file_history: Any = None) -> ToolRegistry:
    from koko_pi_agent.tools.bash import Bash
    from koko_pi_agent.tools.edit_file import EditFile
    from koko_pi_agent.tools.file_state_cache import FileStateCache
    from koko_pi_agent.tools.glob import Glob
    from koko_pi_agent.tools.grep import Grep
    from koko_pi_agent.tools.read_file import ReadFile
    from koko_pi_agent.tools.write_file import WriteFile

    file_state_cache = FileStateCache()

    registry = ToolRegistry()
    registry.register(ReadFile(file_state_cache=file_state_cache))
    registry.register(
        WriteFile(file_history=file_history, file_state_cache=file_state_cache)
    )
    registry.register(
        EditFile(file_history=file_history, file_state_cache=file_state_cache)
    )
    registry.register(Bash())
    registry.register(Glob())
    registry.register(Grep())
    return registry
