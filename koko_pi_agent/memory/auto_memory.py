# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""自动记忆管理器。

使用独立 .md 文件 + frontmatter + MEMORY.md 索引的存储格式，
替代旧版集中式 memories.md。每条记忆存为一个文件，MEMORY.md
只保存索引指针。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from koko_pi_agent.conversation import ConversationManager, Message

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 记忆索引文件名
ENTRYPOINT_NAME = "MEMORY.md"

# 四种记忆类型
VALID_TYPES = {"user", "feedback", "project", "reference"}

# 记忆类型到存储目录的路由：user/feedback → 用户级，project/reference → 项目级
_USER_LEVEL_TYPES = {"user", "feedback"}
_PROJECT_LEVEL_TYPES = {"project", "reference"}

# MEMORY.md 截断限制
MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000

# frontmatter 正则
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# 路径工具函数
# ---------------------------------------------------------------------------

def get_auto_mem_path(project_root: str) -> str:
    """返回项目级记忆目录路径：<projectRoot>/.koko/memory/。

    保留尾部分隔符，确保前缀匹配不会误命中类似 memoryxyz 的路径。
    支持 MEWCODE_REMOTE_MEMORY_DIR 环境变量覆盖。
    """
    override = os.environ.get("MEWCODE_REMOTE_MEMORY_DIR", "")
    if override:
        return override.rstrip(os.sep) + os.sep
    abs_root = os.path.abspath(project_root)
    return os.path.join(abs_root, ".koko", "memory") + os.sep


def get_user_auto_mem_path() -> str:
    """返回用户级记忆目录路径：~/.koko/memory/。

    用于存储 type=user / type=feedback 的记忆，跨项目跟随用户。
    如果 HOME 无法解析则返回空字符串。
    """
    try:
        home = str(Path.home())
    except RuntimeError:
        return ""
    if not home:
        return ""
    return os.path.join(home, ".koko", "memory") + os.sep


def is_auto_mem_path(absolute_path: str, project_root: str) -> bool:
    """检查路径是否在项目级或用户级记忆目录内。"""
    abs_p = os.path.normpath(absolute_path) + os.sep
    project_dir = get_auto_mem_path(project_root)
    if project_dir and abs_p.startswith(project_dir):
        return True
    user_dir = get_user_auto_mem_path()
    if user_dir and abs_p.startswith(user_dir):
        return True
    return False


def ensure_memory_dir_exists(memory_dir: str) -> None:
    """确保记忆目录存在，agent 可直接写入无需先 mkdir。"""
    if memory_dir:
        os.makedirs(memory_dir, exist_ok=True)


# ---------------------------------------------------------------------------
# Frontmatter 解析
# ---------------------------------------------------------------------------

@dataclass
class MemoryFile:
    """一个记忆文件的元信息。"""
    path: str = ""
    name: str = ""
    description: str = ""
    type: str = ""


def parse_frontmatter(content: str) -> MemoryFile:
    """从 YAML-ish frontmatter 中提取 name/description/type。

    只读取三个已知字段，未知字段忽略。没有 frontmatter 的文件返回空字段。
    """
    mf = MemoryFile()
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return mf
    for line in m.group(1).split("\n"):
        colon = line.find(":")
        if colon < 0:
            continue
        key = line[:colon].strip()
        val = line[colon + 1:].strip()
        # 去除引号
        if len(val) >= 2 and (
            (val.startswith('"') and val.endswith('"'))
            or (val.startswith("'") and val.endswith("'"))
        ):
            val = val[1:-1]
        if key == "name":
            mf.name = val
        elif key == "description":
            mf.description = val
        elif key == "type" and val in VALID_TYPES:
            mf.type = val
    return mf


# ---------------------------------------------------------------------------
# MEMORY.md 截断
# ---------------------------------------------------------------------------

def _cut_to_bytes(data: bytes, limit: int) -> str:
    """把 UTF-8 字节串截到 limit 字节以内再解码回字符串。

    优先切在 limit 之前的最后一个换行处，这样留下的都是完整条目。UTF-8 里 ASCII
    字节不会出现在多字节字符内部，直接按字节找 b"\\n" 是安全的。

    整段没有换行时按字节硬切，errors="ignore" 丢掉末尾被劈开的半个字符，
    避免解码出替换符污染索引。
    """
    nl = data.rfind(b"\n", 0, limit)
    if nl > 0:
        return data[:nl].decode("utf-8")
    return data[:limit].decode("utf-8", errors="ignore")


def truncate_entrypoint_content(raw: str) -> str:
    """截断 MEMORY.md 内容，超过行数或字节限制时添加警告。

    先按行截断，行是索引的天然边界。行截断之后再量字节，因为单行可以很长，
    200 行仍然可能超出字节上限，中文条目尤其容易，一个汉字占三字节。
    """
    trimmed = raw.strip()
    lines = trimmed.split("\n")
    line_count = len(lines)
    byte_count = len(trimmed.encode("utf-8"))

    over_lines = line_count > MAX_ENTRYPOINT_LINES
    over_bytes = byte_count > MAX_ENTRYPOINT_BYTES

    if not over_lines and not over_bytes:
        return trimmed

    result = trimmed
    if over_lines:
        result = "\n".join(lines[:MAX_ENTRYPOINT_LINES])

    result_bytes = result.encode("utf-8")
    if len(result_bytes) > MAX_ENTRYPOINT_BYTES:
        result = _cut_to_bytes(result_bytes, MAX_ENTRYPOINT_BYTES)

    # 构建警告信息
    if over_bytes and not over_lines:
        reason = f"{_format_size(byte_count)} (limit: {_format_size(MAX_ENTRYPOINT_BYTES)}) — index entries are too long"
    elif over_lines and not over_bytes:
        reason = f"{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})"
    else:
        reason = f"{line_count} lines and {_format_size(byte_count)}"

    result += (
        f"\n\n> WARNING: {ENTRYPOINT_NAME} is {reason}. "
        "Only part of it was loaded. Keep index entries to one line "
        "under ~200 chars; move detail into topic files."
    )
    return result


def _format_size(byte_count: int) -> str:
    if byte_count < 1024:
        return f"{byte_count}B"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f}KB"
    else:
        return f"{byte_count / (1024 * 1024):.1f}MB"


# ---------------------------------------------------------------------------
# 构建记忆系统提示
# ---------------------------------------------------------------------------

def build_memory_prompt(user_mem_dir: str, project_mem_dir: str) -> str:
    """构建记忆系统提示，包含行为指令和 MEMORY.md 索引内容。

    组合类型化记忆行为指令 + 两个 MEMORY.md
    的内容，生成完整的 '# auto memory' 系统提示段。
    """
    lines = _build_memory_lines(user_mem_dir, project_mem_dir)
    parts = [lines]

    if user_mem_dir:
        ep_path = os.path.join(user_mem_dir, ENTRYPOINT_NAME)
        parts.append("")
        parts.append(_build_entrypoint_section("User-level", ep_path))

    if project_mem_dir:
        ep_path = os.path.join(project_mem_dir, ENTRYPOINT_NAME)
        parts.append("")
        parts.append(_build_entrypoint_section("Project-level", ep_path))

    return "\n".join(parts)


def _build_entrypoint_section(scope_label: str, entrypoint_path: str) -> str:
    """读取一个 MEMORY.md 文件并格式化为系统提示段。"""
    header = f"## {scope_label} {ENTRYPOINT_NAME} (`{entrypoint_path}`)\n"
    try:
        data = Path(entrypoint_path).read_text(encoding="utf-8")
        if data.strip():
            return header + "\n" + truncate_entrypoint_content(data)
    except OSError:
        pass
    return header + f"\nThis {ENTRYPOINT_NAME} is currently empty. When you save new {scope_label.lower()}-level memories, add their pointers here."


def _build_memory_lines(user_mem_dir: str, project_mem_dir: str) -> str:
    """构建类型化记忆的行为指令文本（不含 MEMORY.md 内容）。"""
    dir_exists_guidance = (
        "This directory already exists — write to it directly with the Write tool "
        "(do not run mkdir or check for its existence)."
    )

    parts = ["# auto memory\n"]
    parts.append(
        "You have a persistent, file-based memory system organized into two locations by content type:\n"
    )

    if user_mem_dir:
        parts.append(
            f"- **User-level** (`{user_mem_dir}`) — memories with `type: user` or `type: feedback`. "
            f"These follow you across all projects, because they describe the human or how the human likes to work. "
            f"{dir_exists_guidance}"
        )
    if project_mem_dir:
        parts.append(
            f"- **Project-level** (`{project_mem_dir}`) — memories with `type: project` or `type: reference`. "
            f"These belong to the current repo, can be committed for team sharing or git-ignored for personal use. "
            f"{dir_exists_guidance}"
        )

    parts.append(
        "\nThe `type` field in each memory file's frontmatter determines which directory it belongs to "
        "— pick the type first, then write to the matching directory."
    )
    parts.append(
        "\nYou should build up this memory system over time so that future conversations can have "
        "a complete picture of who the user is, how they'd like to collaborate with you, what behaviors "
        "to avoid or repeat, and the context behind the work the user gives you."
    )

    # frontmatter 格式示例
    parts.append("\n## How to save memories\n")
    parts.append(
        "Saving a memory is a two-step process:\n\n"
        "**Step 1** — write the memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) "
        "using this frontmatter format:\n\n"
        "```markdown\n"
        "---\n"
        "name: {{memory name}}\n"
        "description: {{one-line description}}\n"
        "type: {{user, feedback, project, reference}}\n"
        "---\n\n"
        "{{memory content}}\n"
        "```\n\n"
        f"**Step 2** — add a pointer to that file in the `{ENTRYPOINT_NAME}` index in the SAME directory "
        f"as the memory file. `{ENTRYPOINT_NAME}` is an index, not a memory — each entry should be one line, "
        "under ~150 characters: `- [Title](file.md) — one-line hook`. It has no frontmatter. "
        f"Never write memory content directly into `{ENTRYPOINT_NAME}`.\n\n"
        f"- Both `{ENTRYPOINT_NAME}` files are always loaded into your conversation context"
        f" — lines after {MAX_ENTRYPOINT_LINES} each will be truncated, so keep each index concise\n"
        "- Keep the name, description, and type fields in memory files up-to-date with the content\n"
        "- Organize memory semantically by topic, not chronologically\n"
        "- Update or remove memories that turn out to be wrong or outdated\n"
        "- Do not write duplicate memories. First check if there is an existing memory you can update "
        "before writing a new one."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """管理双路径自动记忆目录（用户级 + 项目级）。

    使用独立 .md 文件 + frontmatter + MEMORY.md 索引。
    实际的写入/读取通过 agent 的 Write/Read 工具完成（参考架构），
    此类提供系统提示构建和 /memory 斜杠命令支持。
    """

    def __init__(self, project_root: str) -> None:
        abs_root = os.path.abspath(project_root)
        self._project_root = abs_root
        # 用户级：~/.koko/memory/ — user/feedback 类型记忆
        self._user_mem_dir = get_user_auto_mem_path()
        # 项目级：<projectRoot>/.koko/memory/ — project/reference 类型记忆
        self._mem_dir = get_auto_mem_path(abs_root)
        self._last_extraction_msg_count = 0

    @property
    def user_path(self) -> Path:
        """用户级 MEMORY.md 的路径（兼容旧接口）。"""
        if self._user_mem_dir:
            return Path(os.path.join(self._user_mem_dir, ENTRYPOINT_NAME))
        return Path.home() / ".koko" / "memory" / ENTRYPOINT_NAME

    @property
    def project_path(self) -> Path:
        """项目级 MEMORY.md 的路径（兼容旧接口）。"""
        return Path(os.path.join(self._mem_dir, ENTRYPOINT_NAME))

    @property
    def user_mem_dir(self) -> Path:
        """用户级记忆目录（~/.koko/memory/）。"""
        return Path(self._user_mem_dir.rstrip(os.sep)) if self._user_mem_dir else Path.home() / ".koko" / "memory"

    @property
    def project_mem_dir(self) -> Path:
        """项目级记忆目录（<project>/.koko/memory/）。"""
        return Path(self._mem_dir.rstrip(os.sep))

    def load(self) -> str:
        """构建完整的记忆系统提示。

        确保两个目录存在后，返回包含行为指令和 MEMORY.md 索引内容的
        '# auto memory' 段，用于注入系统提示。
        """
        if not self._mem_dir and not self._user_mem_dir:
            return ""
        # 确保目录存在
        if self._user_mem_dir:
            ensure_memory_dir_exists(self._user_mem_dir)
        if self._mem_dir:
            ensure_memory_dir_exists(self._mem_dir)
        return build_memory_prompt(self._user_mem_dir, self._mem_dir)

    def load_all(self) -> list[MemoryFile]:
        """扫描两个目录中所有 .md 文件（排除 MEMORY.md），解析 frontmatter。

        用户级文件在前，项目级在后。
        """
        result = _load_dir(self._user_mem_dir)
        result.extend(_load_dir(self._mem_dir))
        return result

    def get_memories(self) -> list[str]:
        """返回所有记忆文件的单行摘要，用于 /memory list。

        收集两类记忆目录下所有可解析的 .md 记忆。
        """
        files = self.load_all()
        out: list[str] = []
        for f in files:
            type_tag = f.type if f.type else "?"
            desc = f.description if f.description else Path(f.path).name
            out.append(f"[{type_tag}] {f.name} — {desc}")
        return out

    def _scan_existing_memories(self) -> str:
        """扫描已有记忆文件，生成 manifest 给 LLM 做去重。"""
        entries: list[str] = []
        for dir_path in (self._user_mem_dir, self._mem_dir):
            if not dir_path:
                continue
            d = Path(dir_path)
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if f.name == ENTRYPOINT_NAME or not f.name.endswith(".md"):
                    continue
                try:
                    mf = parse_frontmatter(f.read_text(encoding="utf-8"))
                    type_tag = mf.type or "?"
                    desc = mf.description or f.stem
                    entries.append(f"- [{type_tag}] {f.name}: {desc}")
                except OSError:
                    continue
        return "\n".join(entries)

    async def extract(
        self,
        client: Any,
        conversation: ConversationManager,
        protocol: str,
    ) -> None:
        """触发记忆提取。

        使用裸 LLM 调用 + 结构化输出解析，发送已有记忆 manifest 做去重。
        """
        from koko_pi_agent.tools.base import StreamEnd, TextDelta

        recent = conversation.history[self._last_extraction_msg_count:]
        if not recent:
            return

        conv_lines: list[str] = []
        for msg in recent:
            if msg.role == "user" and msg.content:
                conv_lines.append(f"[user]: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                conv_lines.append(f"[assistant]: {msg.content}")
        if not conv_lines:
            return

        # 扫描已有记忆做去重
        manifest = self._scan_existing_memories()
        manifest_section = ""
        if manifest:
            manifest_section = (
                f"\n\n## Existing memory files\n\n{manifest}\n\n"
                "Check this list before creating — update an existing file rather than creating a duplicate."
            )

        prompt = (
            f"Analyze the conversation below and extract memories worth saving.\n\n"
            f"For each memory, output in this exact format:\n"
            f"MEMORY_NAME: <kebab-case-name>\n"
            f"MEMORY_TYPE: <user|feedback|project|reference>\n"
            f"MEMORY_DESC: <one-line description>\n"
            f"MEMORY_BODY: <content>\n"
            f"---\n\n"
            f"Types:\n"
            f"- user/feedback → save to {self._user_mem_dir}\n"
            f"- project/reference → save to {self._mem_dir}\n\n"
            f"What NOT to save:\n"
            f"- Code patterns derivable from reading the project\n"
            f"- Git history, debugging solutions\n"
            f"- Ephemeral task details\n\n"
            f"If nothing is worth saving, output NONE.{manifest_section}\n\n"
            f"Conversation:\n{''.join(conv_lines)}"
        )

        extract_conv = ConversationManager()
        extract_conv.history = [Message(role="user", content=prompt)]

        collected = ""
        try:
            async for event in client.stream(
                extract_conv, system="You are a memory extraction assistant."
            ):
                if isinstance(event, TextDelta):
                    collected += event.text
                elif isinstance(event, StreamEnd):
                    pass
        except Exception:
            return

        self._last_extraction_msg_count = len(conversation.history)

        # 解析并写入记忆文件
        if not collected or collected.strip() == "NONE" or "MEMORY_NAME:" not in collected:
            return

        blocks = [b for b in collected.split("---") if "MEMORY_NAME:" in b]
        for block in blocks:
            name = _extract_field(block, "MEMORY_NAME")
            mtype = _extract_field(block, "MEMORY_TYPE") or "reference"
            desc = _extract_field(block, "MEMORY_DESC")
            body = _extract_field(block, "MEMORY_BODY")
            if not name or not body:
                continue
            if mtype not in VALID_TYPES:
                mtype = "reference"

            # 路由到正确的目录
            target_dir = self._user_mem_dir if mtype in _USER_LEVEL_TYPES else self._mem_dir
            if not target_dir:
                continue
            ensure_memory_dir_exists(target_dir)

            content = f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: {mtype}\n---\n\n{body}\n"
            file_path = Path(target_dir) / f"{name}.md"
            try:
                file_path.write_text(content, encoding="utf-8")
            except OSError:
                continue

            # 更新 MEMORY.md 索引
            idx_path = Path(target_dir) / ENTRYPOINT_NAME
            idx_line = f"- [{name}]({name}.md) — {desc}\n"
            try:
                existing = idx_path.read_text(encoding="utf-8") if idx_path.exists() else ""
                if f"{name}.md" not in existing:
                    idx_path.write_text(existing + idx_line, encoding="utf-8")
            except OSError:
                pass

    def clear(self) -> None:
        """清除两个目录下所有 .md 文件。"""
        _clear_dir(self._user_mem_dir)
        _clear_dir(self._mem_dir)

    def get_display_text(self) -> str:
        """返回记忆摘要文本（/memory 命令显示）。"""
        memories = self.get_memories()
        if not memories:
            return "当前没有任何自动记忆。"

        parts: list[str] = []
        parts.append(f"记忆目录：")
        parts.append(f"  用户级: {self._user_mem_dir}")
        parts.append(f"  项目级: {self._mem_dir}")
        parts.append("")
        for line in memories:
            parts.append(f"  {line}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _load_dir(dir_path: str) -> list[MemoryFile]:
    """扫描目录中的 .md 文件，解析 frontmatter 并返回 MemoryFile 列表。"""
    if not dir_path:
        return []
    d = Path(dir_path)
    if not d.is_dir():
        return []

    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name)
    except OSError:
        return []

    result: list[MemoryFile] = []
    for entry in entries:
        if entry.is_dir():
            continue
        if entry.name == ENTRYPOINT_NAME or not entry.name.endswith(".md"):
            continue
        try:
            data = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        mf = parse_frontmatter(data)
        mf.path = str(entry)
        if not mf.name:
            mf.name = entry.stem  # 去掉 .md 后缀
        result.append(mf)
    return result


def _extract_field(block: str, field: str) -> str:
    """从记忆提取输出的一个 block 中提取指定字段值。"""
    m = re.search(rf"{field}:\s*(.+?)(?:\n|$)", block)
    return m.group(1).strip() if m else ""


def _clear_dir(dir_path: str) -> None:
    """删除目录中所有 .md 文件（包括 MEMORY.md）。"""
    if not dir_path:
        return
    d = Path(dir_path)
    if not d.is_dir():
        return
    try:
        for entry in d.iterdir():
            if entry.is_dir() or not entry.name.endswith(".md"):
                continue
            try:
                entry.unlink()
            except OSError:
                pass
    except OSError:
        pass
