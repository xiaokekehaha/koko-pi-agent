# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

from koko_pi_agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from koko_pi_agent.skills.loader import SkillLoader


class InstallSkillParams(BaseModel):
    url: str = Field(
        description=(
            'The Skill URL to fetch. Examples: '
            '"https://www.skills.sh/anthropics/skills/frontend-design", '
            '"https://github.com/anthropics/skills/tree/main/skills/pdf".'
        )
    )


class InstallSkillTool(Tool):
    """从 URL 下载并安装 skill 到用户全局目录 (~/.koko/skills/)。

    支持 skills.sh、GitHub tree、raw.githubusercontent.com 三种 URL 格式。
    安装完成后自动刷新 catalog，新 skill 可通过 /<name> 或 LoadSkill 直接使用。
    """

    name = "InstallSkill"
    description = (
        "Download and install a Skill from a URL into the user-global skills directory "
        "(~/.koko/skills/). Supports skills.sh URLs (https://www.skills.sh/<owner>/<repo>/<name>), "
        "GitHub tree URLs (https://github.com/<owner>/<repo>/tree/<ref>/<path>), and raw "
        "SKILL.md URLs. After install the Skill becomes available via /<name> and LoadSkill. "
        "Call this when the user pastes a Skill URL and asks to install it."
    )
    params_model = InstallSkillParams
    category = "write"

    def __init__(self) -> None:
        self._loader: SkillLoader | None = None
        self._on_installed: Callable[[str], None] | None = None
        self._install_root: str | None = None

    def set_loader(self, loader: SkillLoader) -> None:
        self._loader = loader

    def set_on_installed(self, callback: Callable[[str], None]) -> None:
        """设置安装完成回调（TUI 用来重新注册斜杠命令）。"""
        self._on_installed = callback

    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, InstallSkillParams)

        from koko_pi_agent.skills.install import parse_skill_url, install_skill

        # 解析 URL
        try:
            src = parse_skill_url(params.url)
        except ValueError as e:
            return ToolResult(output=str(e), is_error=True)

        # 执行安装
        try:
            report = await install_skill(src, install_root=self._install_root)
        except Exception as e:
            return ToolResult(output=f"install failed: {e}", is_error=True)

        # 刷新 catalog，让新 skill 立即可用
        if self._loader is not None:
            self._loader.reload()

        if self._on_installed is not None:
            self._on_installed(report.skill_name)

        return ToolResult(
            output=(
                f"Installed skill {report.skill_name!r} from {src.original} "
                f"into {report.target_dir} "
                f"({report.file_count} files, {report.total_bytes} bytes). "
                f"Now available — call LoadSkill({{name: {report.skill_name!r}}}) "
                f"or invoke /{report.skill_name} directly."
            )
        )
