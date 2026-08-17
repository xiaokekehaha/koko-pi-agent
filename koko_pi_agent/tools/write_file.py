# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from koko_pi_agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from koko_pi_agent.tools.file_state_cache import FileStateCache


class Params(BaseModel):
    file_path: str = Field(description="Path to the file to write")
    content: str = Field(description="Content to write to the file")


class WriteFile(Tool):
    name = "WriteFile"
    description = (
        "Write content to a file, creating parent directories if needed. Overwrites existing files.\n"
        "You MUST read existing files with ReadFile before overwriting them. This tool will fail otherwise."
    )
    params_model = Params
    category = "write"


    def __init__(self, file_history: Any = None, file_state_cache: FileStateCache | None = None) -> None:
        self.file_history = file_history
        self._state_cache = file_state_cache


    async def execute(self, params: Params) -> ToolResult:
        if self.file_history is not None:
            self.file_history.track_edit(params.file_path)

        path = Path(params.file_path)

        if self._state_cache and path.exists():
            resolved = str(path.resolve())
            ok, err_msg = self._state_cache.check(resolved)
            if not ok:
                return ToolResult(output=err_msg, is_error=True)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.content, encoding="utf-8")
            if self._state_cache:
                self._state_cache.update(str(path.resolve()))
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)
        return ToolResult(output=f"Successfully wrote to {params.file_path}")
