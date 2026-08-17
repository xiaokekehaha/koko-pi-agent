# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""Skill 系统的测试 —— 包括 parser、loader、executor 以及 LoadSkill 工具。"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from koko_pi_agent.skills.parser import (
    SkillDef,
    SkillParseError,
    parse_frontmatter,
    parse_skill_file,
    substitute_arguments,
)
from koko_pi_agent.skills.loader import SkillLoader
from koko_pi_agent.tools import ToolRegistry

# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

VALID_SKILL_MD = textwrap.dedent("""\
    ---
    name: test-skill
    description: A test skill
    mode: inline
    ---

    # Task

    Do something.

    $ARGUMENTS
""")

FORK_SKILL_MD = textwrap.dedent("""\
    ---
    name: review
    description: Review code
    mode: fork
    context: none
    ---

    Review the code changes.

    $ARGUMENTS
""")


# ---------------------------------------------------------------------------
# Parser 测试
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_valid(self) -> None:
        meta, body = parse_frontmatter(VALID_SKILL_MD)
        assert meta["name"] == "test-skill"
        assert meta["description"] == "A test skill"
        assert "Do something" in body

    def test_missing_opening(self) -> None:
        with pytest.raises(SkillParseError, match="Missing YAML frontmatter"):
            parse_frontmatter("no frontmatter here")

    def test_unclosed(self) -> None:
        with pytest.raises(SkillParseError, match="Unclosed YAML"):
            parse_frontmatter("---\nname: foo\n")

    def test_invalid_yaml(self) -> None:
        with pytest.raises(SkillParseError, match="Invalid YAML"):
            parse_frontmatter("---\n: :\n  bad: [yaml\n---\nbody")

    def test_non_dict_frontmatter(self) -> None:
        with pytest.raises(SkillParseError, match="must be a YAML mapping"):
            parse_frontmatter("---\n- list\n- item\n---\nbody")

class TestParseSkillFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text(VALID_SKILL_MD)
        skill = parse_skill_file(f)
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.mode == "inline"
        assert "$ARGUMENTS" in skill.prompt_body

    def test_legacy_context_fork_maps_to_mode(self, tmp_path: Path) -> None:
        """`context: fork` 与 `mode: fork` 等价，外部生态的技能直接可用。"""
        f = tmp_path / "audit.md"
        f.write_text(
            "---\nname: audit-deps\ndescription: Audit dependencies\ncontext: fork\n---\nbody"
        )
        skill = parse_skill_file(f)
        assert skill.mode == "fork"
        assert skill.context == "full"

    def test_explicit_mode_wins_over_context(self, tmp_path: Path) -> None:
        f = tmp_path / "audit.md"
        f.write_text(
            "---\nname: audit-deps\ndescription: Audit\nmode: inline\ncontext: fork\n---\nbody"
        )
        skill = parse_skill_file(f)
        assert skill.mode == "inline"

    def test_missing_name(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_text("---\ndescription: oops\n---\nbody")
        with pytest.raises(SkillParseError, match="Missing required field 'name'"):
            parse_skill_file(f)

    def test_missing_description(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_text("---\nname: foo\n---\nbody")
        with pytest.raises(SkillParseError, match="Missing required field 'description'"):
            parse_skill_file(f)

    def test_invalid_name_format(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_text("---\nname: UPPER\ndescription: x\n---\nbody")
        with pytest.raises(SkillParseError, match="Invalid skill name"):
            parse_skill_file(f)

    def test_invalid_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_text("---\nname: foo\ndescription: x\nmode: bad\n---\nbody")
        with pytest.raises(SkillParseError, match="Invalid mode"):
            parse_skill_file(f)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(SkillParseError, match="Cannot read"):
            parse_skill_file(tmp_path / "nope.md")

    def test_fork_mode_with_context(self, tmp_path: Path) -> None:
        f = tmp_path / "fork.md"
        f.write_text(FORK_SKILL_MD)
        skill = parse_skill_file(f)
        assert skill.mode == "fork"
        assert skill.context == "none"

class TestSubstituteArguments:
    def test_with_args(self) -> None:
        result = substitute_arguments("Do $ARGUMENTS now", "something cool")
        assert result == "Do something cool now"

    def test_without_args(self) -> None:
        result = substitute_arguments("Do $ARGUMENTS now", "")
        assert result == "Do  now"

    def test_no_placeholder(self) -> None:
        # 无占位符但 args 非空时，append fallback 将用户请求追加到末尾
        result = substitute_arguments("No placeholder here", "args")
        assert result == "No placeholder here\n\n## User Request\n\nargs"

    def test_multiple_placeholders(self) -> None:
        result = substitute_arguments("$ARGUMENTS and $ARGUMENTS", "x")
        assert result == "x and x"

# ---------------------------------------------------------------------------
# Loader 测试
# ---------------------------------------------------------------------------

class TestSkillLoader:
    def test_load_builtins_empty(self) -> None:
        """内置 skill 已移除，load_all 不再返回内置 skill。"""
        loader = SkillLoader("/nonexistent")
        skills = loader.load_all()
        assert "commit" not in skills
        assert "review" not in skills
        assert "test" not in skills
        assert "backend-interview" not in skills

    def test_project_overrides_builtin(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".koko" / "skills"
        skills_dir.mkdir(parents=True)
        custom = skills_dir / "commit.md"
        custom.write_text(textwrap.dedent("""\
            ---
            name: commit
            description: Custom commit
            mode: inline
            ---
            Custom prompt
        """))
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills["commit"].description == "Custom commit"
        assert "Custom prompt" in skills["commit"].prompt_body

    def test_catalog_empty_without_project_skills(self) -> None:
        """无项目/用户 skill 且内置已移除时，catalog 为空。"""
        loader = SkillLoader("/nonexistent")
        loader.load_all()
        catalog = loader.get_catalog()
        assert catalog == []

    def test_get_returns_none_for_removed_builtins(self) -> None:
        """内置 skill 已移除，get 返回 None。"""
        loader = SkillLoader("/nonexistent")
        loader.load_all()
        assert loader.get("commit") is None
        assert loader.get("review") is None
        assert loader.get("test") is None

    def test_get_unknown(self) -> None:
        loader = SkillLoader("/nonexistent")
        loader.load_all()
        assert loader.get("nonexistent") is None

    def test_hot_reload(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".koko" / "skills"
        skills_dir.mkdir(parents=True)
        f = skills_dir / "custom.md"
        f.write_text(textwrap.dedent("""\
            ---
            name: custom
            description: v1
            ---
            Prompt v1
        """))
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        assert loader.get("custom").description == "v1"

        f.write_text(textwrap.dedent("""\
            ---
            name: custom
            description: v2
            ---
            Prompt v2
        """))
        skill = loader.get("custom")
        assert skill.description == "v2"
        assert "v2" in skill.prompt_body

    def test_hot_reload_fallback_on_error(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".koko" / "skills"
        skills_dir.mkdir(parents=True)
        f = skills_dir / "custom.md"
        f.write_text(textwrap.dedent("""\
            ---
            name: custom
            description: good
            ---
            Good prompt
        """))
        loader = SkillLoader(str(tmp_path))
        loader.load_all()

        f.write_text("broken content no frontmatter")
        skill = loader.get("custom")
        assert skill is not None
        assert skill.description == "good"

    def test_directory_skill_detected(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".koko" / "skills"
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: my-skill
            description: A directory skill
            ---
            SOP here
        """))
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert "my-skill" in skills
        assert skills["my-skill"].is_directory is True

    def test_source_label(self, tmp_path: Path) -> None:
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        assert loader.get_source_label("nonexistent") == "unknown"

    def test_malformed_file_skipped(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".koko" / "skills"
        skills_dir.mkdir(parents=True)
        bad = skills_dir / "broken.md"
        bad.write_text("not valid frontmatter")
        good = skills_dir / "valid.md"
        good.write_text(textwrap.dedent("""\
            ---
            name: valid
            description: Works fine
            ---
            Prompt
        """))
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert "valid" in skills
        assert "broken" not in skills

    def test_reload(self, tmp_path: Path) -> None:
        """reload 重新扫描目录，内置已移除时结果为空。"""
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        skills = loader.reload()
        assert isinstance(skills, dict)


# ---------------------------------------------------------------------------
# LoadSkill 工具
# ---------------------------------------------------------------------------

class TestLoadSkillTool:
    @pytest.mark.asyncio
    async def test_load_existing_skill(self) -> None:
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        loader = MagicMock()
        agent = MagicMock()
        agent.registry = ToolRegistry()

        skill = SkillDef(
            name="commit",
            description="Commit",
            prompt_body="Do commit",
            is_directory=False,
        )
        loader.get.return_value = skill

        tool.set_loader(loader)
        tool.set_agent(agent)

        result = await tool.execute(LoadSkillParams(name="commit"))
        assert not result.is_error
        assert "# Skill: commit" in result.output and "Do commit" in result.output
        agent.activate_skill.assert_called_once_with("commit", "Do commit")

    @pytest.mark.asyncio
    async def test_load_unknown_skill(self) -> None:
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        loader = MagicMock()
        loader.get.return_value = None
        loader.get_catalog.return_value = [("commit", "x")]
        agent = MagicMock()

        tool.set_loader(loader)
        tool.set_agent(agent)

        result = await tool.execute(LoadSkillParams(name="nonexistent"))
        assert result.is_error
        assert "unknown skill" in result.output

    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        result = await tool.execute(LoadSkillParams(name="test"))
        assert result.is_error
        assert "not properly initialized" in result.output

    @pytest.mark.asyncio
    async def test_fork_skill_runs_in_sub_agent(self) -> None:
        """fork 模式下 SOP 正文交给子 Agent，主对话只拿到最终结果。"""
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        loader = MagicMock()
        agent = MagicMock()
        executor = MagicMock()
        executor.execute_fork = AsyncMock(return_value="3 risky pins found")

        loader.get.return_value = SkillDef(
            name="audit-deps",
            description="Audit dependencies",
            prompt_body="Inspect pyproject.toml and flag risky pins.",
            mode="fork",
        )

        tool.set_loader(loader)
        tool.set_agent(agent)
        tool.set_executor(executor)

        result = await tool.execute(LoadSkillParams(name="audit-deps"))
        assert not result.is_error
        assert result.output == "3 risky pins found"
        assert "Inspect pyproject.toml" not in result.output
        executor.execute_fork.assert_awaited_once()
        agent.activate_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_fork_skill_falls_back_without_executor(self) -> None:
        """宿主没有接入执行器时回退成 inline，工具仍然可用。"""
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        loader = MagicMock()
        agent = MagicMock()

        loader.get.return_value = SkillDef(
            name="audit-deps",
            description="Audit dependencies",
            prompt_body="Inspect pyproject.toml and flag risky pins.",
            mode="fork",
        )

        tool.set_loader(loader)
        tool.set_agent(agent)

        result = await tool.execute(LoadSkillParams(name="audit-deps"))
        assert not result.is_error
        assert "Inspect pyproject.toml" in result.output
        agent.activate_skill.assert_called_once()

    @pytest.mark.asyncio
    async def test_inline_skill_does_not_fork(self) -> None:
        """inline 模式保持原样：返回 SOP 正文，不启子 Agent。"""
        from koko_pi_agent.tools.load_skill import LoadSkill, LoadSkillParams

        tool = LoadSkill()
        loader = MagicMock()
        agent = MagicMock()
        executor = MagicMock()
        executor.execute_fork = AsyncMock(return_value="should not be used")

        loader.get.return_value = SkillDef(
            name="commit",
            description="Commit",
            prompt_body="Write a conventional commit message.",
            mode="inline",
        )

        tool.set_loader(loader)
        tool.set_agent(agent)
        tool.set_executor(executor)

        result = await tool.execute(LoadSkillParams(name="commit"))
        assert "Write a conventional commit message." in result.output
        executor.execute_fork.assert_not_awaited()

    def test_load_skill_is_read_only(self) -> None:
        from koko_pi_agent.tools.load_skill import LoadSkill

        tool = LoadSkill()
        assert tool.category == "read"

# ---------------------------------------------------------------------------
# Agent 集成
# ---------------------------------------------------------------------------

class TestAgentSkillIntegration:
    def test_env_context_does_not_include_active_skills(self) -> None:
        from koko_pi_agent.prompts import build_environment_context

        env = build_environment_context(
            "/test",
            active_skills={"commit": "Do commit stuff"},
            skill_catalog="Available: commit",
        )
        assert "Active Skills" not in env
        assert "Do commit stuff" not in env
        assert "Available: commit" in env

    def test_agent_activate_and_clear(self) -> None:
        agent = MagicMock()
        agent.active_skills = {}

        from koko_pi_agent.agent import Agent

        real_agent = MagicMock(spec=Agent)
        real_agent.active_skills = {}
        real_agent.activate_skill = Agent.activate_skill.__get__(real_agent)
        real_agent.clear_active_skills = Agent.clear_active_skills.__get__(real_agent)

        real_agent.activate_skill("test", "SOP")
        assert "test" in real_agent.active_skills

        real_agent.clear_active_skills()
        assert len(real_agent.active_skills) == 0
