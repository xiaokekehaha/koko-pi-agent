# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mewcode.memory.instructions import process_includes

log = logging.getLogger(__name__)

# 不限制模型白名单：第三方模型名称（如 "glm-5.1"）需要能直通路由层，
# 实际可用性由 ModelResolver / LLM 路由决定
VALID_MODELS: set[str] | None = None  # None 表示接受任意非空字符串
VALID_PERMISSION_MODES = {"default", "acceptEdits", "bypassPermissions", ""}


class AgentParseError(Exception):
    pass


VALID_ISOLATION_MODES = {"", "worktree"}


@dataclass
class AgentDef:
    agent_type: str
    when_to_use: str
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 200  # 未指定时的默认值
    permission_mode: str = "default"
    background: bool = False
    isolation: str = ""
    file_path: Path | None = None
    source: str = "builtin"


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    stripped = raw.lstrip()
    if not stripped.startswith("---"):
        raise AgentParseError("Missing YAML frontmatter (must start with ---)")

    end = stripped.find("---", 3)
    if end == -1:
        raise AgentParseError("Unclosed YAML frontmatter (missing closing ---)")

    yaml_block = stripped[3:end]
    body = stripped[end + 3 :].lstrip("\n")

    try:
        meta = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        raise AgentParseError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(meta, dict):
        raise AgentParseError("Frontmatter must be a YAML mapping")

    return meta, body


def _validate_agent_meta(meta: dict, source: str = "") -> None:
    ctx = f" in {source}" if source else ""

    if "name" not in meta:
        raise AgentParseError(f"Missing required field 'name'{ctx}")
    if "description" not in meta:
        raise AgentParseError(f"Missing required field 'description'{ctx}")

    # model 字段：只做 "inherit" 大小写归一化，不限制具体值
    # 第三方模型名称（如 "glm-5.1"）由宿主的 ModelResolver 负责校验
    model = str(meta.get("model", "inherit")).strip()
    if model.lower() == "inherit":
        meta["model"] = "inherit"

    pm = str(meta.get("permissionMode", "default"))
    if pm not in VALID_PERMISSION_MODES:
        raise AgentParseError(
            f"Invalid permissionMode '{pm}'{ctx}: "
            f"must be one of {VALID_PERMISSION_MODES - {''}}"
        )

    max_turns = meta.get("maxTurns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns <= 0:
            raise AgentParseError(
                f"Invalid maxTurns '{max_turns}'{ctx}: must be a positive integer"
            )

    isolation = str(meta.get("isolation", ""))
    if isolation not in VALID_ISOLATION_MODES:
        raise AgentParseError(
            f"Invalid isolation '{isolation}'{ctx}: "
            f"must be one of {VALID_ISOLATION_MODES - {''}}"
        )


def parse_agent_file(path: Path) -> AgentDef:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise AgentParseError(f"Cannot read agent file {path}: {e}") from e

    meta, body = parse_frontmatter(raw)
    _validate_agent_meta(meta, str(path))

    # 展开 @ 引用指令（围栏代码块内的 @ 引用会自动跳过，
    # 由 process_includes 的 in_code 逻辑保证）
    base_dir = path.parent
    project_root = base_dir
    body = process_includes(body, base_dir, project_root)

    return AgentDef(
        agent_type=meta["name"],
        when_to_use=meta["description"],
        system_prompt=body,
        tools=meta.get("tools", []),
        disallowed_tools=meta.get("disallowedTools", []),
        model=str(meta.get("model", "inherit")),
        max_turns=meta.get("maxTurns") or 200,  # 未指定时默认 200
        permission_mode=str(meta.get("permissionMode", "default")),
        background=bool(meta.get("background", False)),
        isolation=str(meta.get("isolation", "")),
        file_path=path,
        source="builtin",
    )
