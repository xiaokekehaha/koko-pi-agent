# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if __import__("typing").TYPE_CHECKING:
    from mewcode.tools import ToolRegistry


class ToolSearchParams(BaseModel):
    query: str
    max_results: int = 5


class ToolSearchTool(Tool):
    name = "ToolSearch"
    description = (
        "Search for and load additional tools that are not immediately available. "
        "Use query 'select:<name>[,<name>...]' to load specific tools by name, "
        "or provide keywords to search by relevance."
    )
    params_model = ToolSearchParams
    category = "read"
    should_defer = False  # ToolSearch 自身永远不延迟加载


    def __init__(
        self,
        registry: ToolRegistry,
        protocol: str = "anthropic",
    ) -> None:
        self._registry = registry
        self._protocol = protocol


    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }


    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, ToolSearchParams)
        query = params.query
        max_results = params.max_results

        if query.startswith("select:"):
            names = [n.strip() for n in query[7:].split(",")]
            schemas = self._registry.find_deferred_by_names(names, self._protocol)
        else:
            schemas = self._registry.search_deferred(
                query, max_results, self._protocol
            )

        if not schemas:
            deferred_names = self._registry.get_deferred_tool_names()
            return ToolResult(
                output=(
                    f'No matching deferred tools for "{query}". '
                    f'Available: {", ".join(deferred_names)}'
                )
            )

        for s in schemas:
            if "name" in s:
                self._registry.mark_discovered(s["name"])

        return ToolResult(
            output=(
                f"Found {len(schemas)} tool(s). Their full schemas are now loaded:\n\n"
                f"{json.dumps(schemas, indent=2, ensure_ascii=False)}"
            )
        )
