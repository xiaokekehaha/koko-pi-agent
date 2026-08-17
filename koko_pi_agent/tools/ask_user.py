# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from koko_pi_agent.tools.base import Tool, ToolResult


class QuestionItem(BaseModel):
    type: str = Field(description="Question type: text, radio, select, checkbox")
    name: str = Field(description="Question identifier")
    message: str = Field(description="Question text to display")
    options: list[str] = Field(
        default_factory=list,
        description="Options for radio/select/checkbox types",
    )


class AskUserParams(BaseModel):
    questions: list[QuestionItem] = Field(
        description="List of questions to ask the user"
    )


class AskUserEvent:


    def __init__(
        self,
        questions: list[dict[str, Any]],
        future: asyncio.Future[dict[str, str]],
    ) -> None:
        self.questions = questions
        self.future = future


class AskUserTool(Tool):
    name = "AskUserQuestion"
    description = (
        "Ask the user one or more questions when you need information "
        "that cannot be determined from code or context alone. Supports "
        "text input, radio (single select), select, and checkbox (multi select) "
        "question types."
    )
    params_model = AskUserParams
    category: str = "read"


    def __init__(self) -> None:
        self._pending_event: AskUserEvent | None = None

    async def execute(self, params: AskUserParams) -> ToolResult:
        questions_data = [q.model_dump() for q in params.questions]

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()

        self._pending_event = AskUserEvent(questions=questions_data, future=future)

        try:
            answers = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            return ToolResult(
                output="User did not respond within 5 minutes", is_error=True
            )
        finally:
            self._pending_event = None

        lines = []
        for q in params.questions:
            answer = answers.get(q.name, "(no answer)")
            lines.append(f"{q.name}: {answer}")

        return ToolResult(output="\n".join(lines))
