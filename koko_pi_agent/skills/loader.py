# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from koko_pi_agent.skills.parser import (
    SkillDef,
    SkillParseError,
    resolve_mode_and_context,
    parse_skill_file,
)

log = logging.getLogger(__name__)

PROJECT_SKILLS_DIR = ".koko/skills"
USER_SKILLS_DIR = "~/.koko/skills"


class SkillLoader:
    def __init__(self, work_dir: str) -> None:
        self._work_dir = work_dir
        self._project_dir = Path(work_dir) / PROJECT_SKILLS_DIR
        self._user_dir = Path(USER_SKILLS_DIR).expanduser()
        self._skills: dict[str, SkillDef] = {}
        self._cache: dict[str, SkillDef] = {}
        self._dir_mod_times: dict[str, float] = {}


    def load_all(self) -> dict[str, SkillDef]:
        seen: dict[str, SkillDef] = {}

        for skill in self._scan_directory(self._project_dir, "project"):
            if skill.name not in seen:
                seen[skill.name] = skill

        for skill in self._scan_directory(self._user_dir, "user"):
            if skill.name not in seen:
                seen[skill.name] = skill

        for skill in self._load_builtins():
            if skill.name not in seen:
                seen[skill.name] = skill

        self._skills = seen
        self._cache = {k: v for k, v in seen.items()}
        self._snapshot_dir_mod_times()
        return seen


    def _scan_directory(self, path: Path, source: str) -> list[SkillDef]:
        results: list[SkillDef] = []
        if not path.is_dir():
            return results

        for entry in sorted(path.iterdir()):
            try:
                if entry.is_file() and entry.suffix == ".md":
                    skill = parse_skill_file(entry)
                    skill.source_path = entry
                    results.append(skill)
                elif entry.is_dir():
                    # 优先尝试 skill.yaml + prompt.md 格式
                    skill_yaml = entry / "skill.yaml"
                    if skill_yaml.is_file():
                        skill = self._parse_skill_yaml(skill_yaml, entry)
                        if skill is not None:
                            results.append(skill)
                            continue
                    # 回退到 SKILL.md 格式
                    skill_md = entry / "SKILL.md"
                    if skill_md.is_file():
                        skill = parse_skill_file(skill_md)
                        skill.source_path = skill_md
                        skill.is_directory = True
                        results.append(skill)
            except SkillParseError as e:
                log.warning("Skipping %s skill '%s': %s", source, entry.name, e)

        return results

    @staticmethod
    def _parse_skill_yaml(yaml_path: Path, skill_dir: Path) -> SkillDef | None:
        """解析 skill.yaml + prompt.md 格式的 skill。"""
        try:
            data = yaml_path.read_text(encoding="utf-8")
            meta = yaml.safe_load(data)
        except (OSError, yaml.YAMLError) as e:
            log.warning("Cannot parse %s: %s", yaml_path, e)
            return None

        if not isinstance(meta, dict):
            log.warning("Invalid skill.yaml in %s: not a mapping", skill_dir)
            return None

        name = meta.get("name", "")
        if not name:
            # 自动从目录名派生
            name = skill_dir.name.lower().replace(" ", "-")

        description = meta.get("description", "")

        # 读取 prompt.md 作为 prompt body
        prompt_md = skill_dir / "prompt.md"
        prompt_body = ""
        if prompt_md.is_file():
            try:
                prompt_body = prompt_md.read_text(encoding="utf-8")
            except OSError as e:
                log.warning("Cannot read prompt.md in %s: %s", skill_dir, e)

        # 没有 description 时从 prompt body 推断
        if not description and prompt_body:
            for line in prompt_body.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    description = line
                    break

        mode, context = resolve_mode_and_context(meta)
        if mode not in ("inline", "fork"):
            mode = "inline"

        return SkillDef(
            name=name,
            description=description,
            prompt_body=prompt_body,
            mode=mode,
            model=meta.get("model"),
            context=context,
            source_path=prompt_md if prompt_md.is_file() else yaml_path,
            is_directory=True,
        )

    def _load_builtins(self) -> list[SkillDef]:
        """内置 skill 已移除，返回空列表。"""
        return []


    def get(self, name: str) -> SkillDef | None:
        skill = self._skills.get(name)
        if skill is None:
            return None

        if skill.source_path is not None:
            try:
                fresh = parse_skill_file(skill.source_path)
                fresh.is_directory = skill.is_directory
                self._skills[name] = fresh
                self._cache[name] = fresh
                return fresh
            except SkillParseError as e:
                log.warning(
                    "Hot-reload failed for skill '%s', using cached version: %s",
                    name, e,
                )
                return self._cache.get(name, skill)

        return skill

    def get_catalog(self) -> list[tuple[str, str]]:
        return [(s.name, s.description) for s in self._skills.values()]

    def needs_reload(self) -> bool:
        """skill 目录的 modtime 变化说明有新增或删除的 skill。"""
        for dir_path, recorded in self._dir_mod_times.items():
            try:
                current = os.stat(dir_path).st_mtime
                if current != recorded:
                    return True
            except OSError:
                if recorded != 0.0:
                    return True
        # 检查之前不存在的目录是否已创建
        for d in [str(self._user_dir), str(self._project_dir)]:
            if d not in self._dir_mod_times:
                try:
                    os.stat(d)
                    return True
                except OSError:
                    pass
        return False

    def _snapshot_dir_mod_times(self) -> None:
        self._dir_mod_times = {}
        for d in [str(self._user_dir), str(self._project_dir)]:
            try:
                self._dir_mod_times[d] = os.stat(d).st_mtime
            except OSError:
                self._dir_mod_times[d] = 0.0

    def reload(self) -> dict[str, SkillDef]:
        return self.load_all()


    def get_source_label(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            return "unknown"
        if skill.source_path is None:
            return "builtin"
        path_str = str(skill.source_path)
        if path_str.startswith(str(self._project_dir)):
            return "project"
        if path_str.startswith(str(self._user_dir)):
            return "user"
        return "builtin"
