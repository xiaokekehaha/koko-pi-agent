from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, Field

from examples.mini_pi_agent.models import ToolResult


class CalculatorParams(BaseModel):
    operator: Literal["add", "subtract", "multiply", "divide"]
    left: float
    right: float


class CalculatorTool:
    name = "calculator"
    description = "Perform one arithmetic operation on two numbers."
    params_model = CalculatorParams

    async def execute(self, params: BaseModel) -> ToolResult:
        values = cast(CalculatorParams, params)
        if values.operator == "add":
            answer = values.left + values.right
        elif values.operator == "subtract":
            answer = values.left - values.right
        elif values.operator == "multiply":
            answer = values.left * values.right
        else:
            if values.right == 0:
                return ToolResult("division by zero is not allowed", is_error=True)
            answer = values.left / values.right
        return ToolResult(str(answer))


class TextLengthParams(BaseModel):
    text: str = Field(min_length=1)


class TextLengthTool:
    name = "text_length"
    description = "Count the number of Python characters in a piece of text."
    params_model = TextLengthParams

    async def execute(self, params: BaseModel) -> ToolResult:
        values = cast(TextLengthParams, params)
        return ToolResult(str(len(values.text)))
