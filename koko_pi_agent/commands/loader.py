# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""从 .koko/commands/ 目录加载自定义 Markdown 命令。

每个 .md 文件对应一个 prompt 类型命令，文件名（去掉后缀、小写化）即命令名。
支持可选的 YAML frontmatter（description / argument-hint / aliases）。
子目录用冒号拼接命名空间，例如 git/log.md -> "git:log"。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from koko_pi_agent.commands.registry import Command, CommandContext, CommandType

log = logging.getLogger(__name__)


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """分离 YAML frontmatter 和 Markdown 正文。"""
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return {}, content
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    return meta, parts[2]


def _first_non_header_line(body: str) -> str:
    """提取第一行非空、非标题行作为描述回退值。"""
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def _make_prompt_handler(body: str):
    """构建 prompt 类型命令的处理函数。

    支持 $ARGUMENTS 占位符替换；若正文没有占位符且用户给了参数，
    追加 "## User Request" 段落。
    """
    async def handler(ctx: CommandContext) -> None:
        if "$ARGUMENTS" in body:
            result = body.replace("$ARGUMENTS", ctx.args)
        elif ctx.args.strip():
            # 无占位符时追加用户请求段落
            result = body + "\n\n## User Request\n\n" + ctx.args
        else:
            result = body
        ctx.ui.send_user_message(result)

    return handler


def load_dir(directory: str) -> list[Command]:
    """递归扫描目录下的 .md 文件，每个文件生成一个 Command。"""
    if not directory:
        return []
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return []

    commands: list[Command] = []
    for root, _dirs, files in os.walk(directory):
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            fpath = Path(root) / fname
            cmd = _parse_command_file(dir_path, fpath)
            if cmd is not None:
                commands.append(cmd)
    return commands


def _parse_command_file(base_dir: Path, path: Path) -> Command | None:
    """解析单个 .md 命令文件。"""
    try:
        data = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        rel = path.relative_to(base_dir)
    except ValueError:
        return None

    # 命令名：去掉 .md 后缀，子目录用冒号连接，全部小写
    parts = list(rel.parts)
    parts[-1] = parts[-1].removesuffix(".md")
    parts = [p.lower().replace(" ", "-") for p in parts]
    name = ":".join(parts)
    if not name:
        return None

    meta, body = _split_frontmatter(data)
    body = body.strip()

    description = meta.get("description", "")
    if not description:
        description = _first_non_header_line(body)

    aliases = meta.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []

    arg_prompt = meta.get("argument-hint", "")

    return Command(
        name=name,
        description=description or f"Custom command: {name}",
        type=CommandType.PROMPT,
        handler=_make_prompt_handler(body),
        aliases=aliases,
        arg_prompt=arg_prompt,
    )


def load_user_commands(work_dir: str) -> list[Command]:
    """从用户全局和项目级目录合并加载自定义命令。

    搜索路径（后者覆盖前者）：
      1. ~/.koko/commands/
      2. <work_dir>/.koko/commands/
    """
    dirs: list[str] = []
    home = Path.home()
    dirs.append(str(home / ".koko" / "commands"))
    dirs.append(str(Path(work_dir) / ".koko" / "commands"))

    merged: dict[str, Command] = {}
    order: list[str] = []
    for d in dirs:
        for cmd in load_dir(d):
            if cmd.name not in merged:
                order.append(cmd.name)
            merged[cmd.name] = cmd

    return [merged[n] for n in order]
