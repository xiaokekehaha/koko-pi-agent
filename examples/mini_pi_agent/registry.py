from __future__ import annotations

from typing import Any

from examples.mini_pi_agent.contracts import Tool


class ToolRegistry:
    """A fail-fast name-to-tool directory."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            parameters = tool.params_model.model_json_schema()
            parameters.pop("title", None)
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": parameters,
                }
            )
        return schemas

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)
