# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.skills.executor import SkillExecutor
    from mewcode.skills.loader import SkillLoader


class LoadSkillParams(BaseModel):
    name: str = Field(description="The name of the skill to load")


class LoadSkill(Tool):
    name = "LoadSkill"
    description = (
        "Load and activate a skill by name. "
        "Returns the full SOP body so you can follow its instructions."
    )
    params_model = LoadSkillParams
    category = "read"
    is_concurrency_safe = False


    def __init__(self) -> None:
        self._loader: SkillLoader | None = None
        self._agent: Agent | None = None
        self._executor: SkillExecutor | None = None


    def set_loader(self, loader: SkillLoader) -> None:
        self._loader = loader

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def set_executor(self, executor: SkillExecutor) -> None:
        """注入执行器，mode: fork 的 skill 靠它跑隔离子 Agent。

        未注入时 fork 会回退成 inline，保证工具在任何宿主上都能用。
        """
        self._executor = executor


    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, LoadSkillParams)

        if self._loader is None or self._agent is None:
            return ToolResult(
                output="Error: LoadSkill not properly initialized",
                is_error=True,
            )

        skill = self._loader.get(params.name)
        if skill is None:
            available = ", ".join(n for n, _ in self._loader.get_catalog())
            return ToolResult(
                output=f"Error: unknown skill '{params.name}'. Available skills: {available}",
                is_error=True,
            )

        # fork 模式：SOP 正文不进主对话，交给隔离的子 Agent 执行，只把最终结果带回。
        # 这样模型自己加载 skill 和用户敲斜杠命令遵循同一套 mode 语义，声明的隔离
        # 意图在两条路径上都生效。
        if skill.mode == "fork" and self._executor is not None:
            try:
                result = await self._executor.execute_fork(skill, "")
            except Exception as e:
                return ToolResult(
                    output=f"Skill '{skill.name}' fork execution failed: {e}",
                    is_error=True,
                )
            return ToolResult(output=result)

        self._agent.activate_skill(skill.name, skill.prompt_body)

        header = f"# Skill: {skill.name}\n\n"
        return ToolResult(output=header + skill.prompt_body)
