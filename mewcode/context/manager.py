# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mewcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
    estimate_tokens,
)
from mewcode.serialization import build_messages

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 单条消息内所有工具结果的聚合上限。单条结果的大小由 tools.MAX_OUTPUT_CHARS
# 在结果入历史时把关，这里只管聚合——一轮并行调多个工具时，每条都没超单条
# 阈值，加起来却能撑爆上下文，这是单条阈值管不到的场景。
AGGREGATE_CHAR_LIMIT = 200_000
PREVIEW_CHARS = 2_000

SUMMARY_OUTPUT_RESERVE = 20_000
# 软触发安全边距：effectiveWindow − 13K 为自动压缩触发线，走熔断器保护
AUTO_COMPACT_SAFETY_MARGIN = 13_000
# 硬触发安全边距：effectiveWindow − 3K 为强制压缩触发线，绕过熔断器
MANUAL_COMPACT_SAFETY_MARGIN = 3_000

# Layer 2 "保留近期原文"窗口。压缩时，尾部消息按 token 累计不超过
# KEEP_RECENT_TOKENS、或消息数不少于 MIN_KEEP_MESSAGES（取先满足的条件保底）保留原文，
# 不纳入摘要。累计超过 KEEP_MAX_TOKENS 时停止，防止单条超大消息吞掉整个窗口。
KEEP_RECENT_TOKENS = 10_000
MIN_KEEP_MESSAGES = 5
KEEP_MAX_TOKENS = 40_000

# 前缀 token 数低于此阈值时不值得做摘要——摘要往返的开销比回收的空间还大，
# 退化为不压缩、保留原始历史（避免「压了个寂寞」）。
MIN_SUMMARIZE_PREFIX_TOKENS = 2_000

PERSISTED_TAG = "<persisted-output>"



# ---------------------------------------------------------------------------
# 事件
# ---------------------------------------------------------------------------


@dataclass
class CompactBoundary:
    """Layer 2 压缩的结构化结果，上交给 session 层处理。

    `summary` 是大模型对被摘要前缀生成的摘要；`keep` 是 auto_compact 原样保留、
    未做改动的近期尾部消息。session 层（持有 sessionId / 文件句柄）会把二者一起
    内联进一条 compact_boundary 记录，这样 resume 时就能重建压缩后的状态。
    用这种方式把写操作解耦出去，能让 auto_compact 保持纯粹、不依赖任何 session。
    """

    summary: str
    keep: list[Message]


@dataclass
class CompactEvent:
    before_tokens: int
    # 摘要成功时填充，调用方可据此持久化 compact_boundary 记录。
    # 未产出摘要时为 None。
    boundary: CompactBoundary | None = None


# ---------------------------------------------------------------------------
# Session 目录管理
# ---------------------------------------------------------------------------

def spill_dir(work_dir: str, session_id: str = "") -> Path:
    """溢写目录：按会话隔离在 .mewcode/sessions/<会话id>/tool-results 下，
    会话 id 为空（一次性调用、测试）时落到 default。"""
    sid = session_id or "default"
    return Path(work_dir) / ".mewcode" / "sessions" / sid / "tool-results"


def ensure_session_dir(work_dir: str, session_id: str = "") -> Path:
    session_dir = spill_dir(work_dir, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def cleanup_tool_results(session_dir: Path) -> None:
    if session_dir.exists():
        shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Layer 1：大型工具结果落盘
# ---------------------------------------------------------------------------

def persist_tool_result(tool_use_id: str, content: str, session_dir: Path) -> Path:
    file_path = session_dir / f"{tool_use_id}.txt"
    try:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        pass
    return file_path


def make_persisted_preview(content: str, file_path: Path) -> str:
    size_kb = len(content) // 1024
    preview = content[:PREVIEW_CHARS]
    more = "\n..." if len(content) > PREVIEW_CHARS else ""
    return (
        f"{PERSISTED_TAG}\n"
        f"输出太大（{size_kb}KB），完整内容已保存到：\n"
        f"{file_path}\n"
        f"\n"
        f"预览（前 2KB）：\n"
        f"{preview}{more}\n"
        f"</persisted-output>"
    )




def is_spill_readback(tool_name: str, arguments: Mapping[str, object], session_dir: Path) -> bool:
    """判断一次工具调用是不是在读回溢写目录下的文件。

    这类结果不做溢写：把模型刚读回来的内容再写盘换成预览，模型就永远
    看不到全文，还会在「读回、溢写」之间打转。
    """
    if tool_name != "ReadFile":
        return False
    raw = arguments.get("file_path", "")
    if not isinstance(raw, str) or not raw:
        return False
    abs_path = os.path.abspath(raw)
    return abs_path.startswith(os.path.abspath(str(session_dir)))


def apply_tool_result_budget(
    tool_results: list[ToolResultBlock],
    session_dir: Path,
    exempt_ids: set[str] | None = None,
) -> None:
    """在一轮工具结果进入对话历史之前执行聚合预算。

    整批结果的总字符数超过 AGGREGATE_CHAR_LIMIT 时，从最大的开始逐条
    溢写到磁盘、就地替换成预览，直到总量回到限额内。消息进历史前处理完，
    历史里的内容自此不再改动，Prompt Cache 前缀天然稳定。

    exempt_ids 里的 tool_use_id 不参与溢写：溢写文件的回读结果（再溢写
    模型就永远看不到全文），以及本轮已经单条溢写过的结果。全是豁免项时
    接受超额。
    """
    exempt = exempt_ids or set()
    total = sum(len(tr.content) for tr in tool_results)
    if total <= AGGREGATE_CHAR_LIMIT:
        return

    # 按内容长度降序挑选：先溢写最大的，回到限额内需要动的条数最少。
    ranked = sorted(tool_results, key=lambda tr: len(tr.content), reverse=True)
    for tr in ranked:
        if total <= AGGREGATE_CHAR_LIMIT:
            break
        if tr.tool_use_id in exempt:
            continue
        if len(tr.content) <= PREVIEW_CHARS:
            # 比预览还短的结果，溢写换不回空间
            continue
        try:
            fp = persist_tool_result(tr.tool_use_id, tr.content, session_dir)
        except OSError:
            # 写盘失败就保留原文。消息随即定型进历史，不会再有重试
            continue
        preview = make_persisted_preview(tr.content, fp)
        total -= len(tr.content) - len(preview)
        tr.content = preview


# ---------------------------------------------------------------------------
# Layer 2：全对话摘要（Auto-Compact）
# ---------------------------------------------------------------------------

def compute_compact_threshold(context_window: int, manual: bool = False) -> int:
    effective = context_window - SUMMARY_OUTPUT_RESERVE
    margin = MANUAL_COMPACT_SAFETY_MARGIN if manual else AUTO_COMPACT_SAFETY_MARGIN
    return effective - margin


SUMMARY_PROMPT = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use ReadFile, Bash, Grep, Glob, EditFile, WriteFile, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

After your analysis, output your final summary wrapped in <summary> tags. Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
8. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
9. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's most recent explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests or really old requests that were already completed without confirming with the user first.
   If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Output structure:

<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]
   - [File Name 2]
      - [Important Code Snippet]
   - [...]

4. Errors and fixes:
    - [Detailed description of error 1]:
      - [How you fixed the error]
      - [User feedback on the error if any]
    - [...]

5. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

6. All user messages:
    - [Detailed non tool use user message]
    - [...]

7. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

8. Current Work:
   [Precise description of current work]

9. Optional Next Step:
   [Optional Next step to take]

</summary>

Please provide your summary based on the conversation so far, following this structure and ensuring precision and thoroughness in your response.

REMINDER: Do NOT call any tools. Respond with plain text only — an <analysis> block followed by a <summary> block. Tool calls will be rejected and you will fail the task."""


def extract_summary(llm_output: str) -> str:
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start == -1 or end == -1:
        return llm_output
    return llm_output[start + len("<summary>"):end].strip()


def build_compact_messages(
    summary: str,
    attachment: str = "",
    has_keep_tail: bool = False,
    transcript_path: str = "",
) -> list[Message]:
    content = "本次会话延续自之前的对话，因上下文空间不足进行了压缩。以下是早期对话的摘要：\n\n" + summary
    if has_keep_tail:
        content += "\n\n近期消息已原样保留。"
    if transcript_path:
        content += f"\n\n如果你需要压缩前的具体细节（代码片段、报错信息等），请用 ReadFile 读取完整会话记录：{transcript_path}"
    if attachment:
        content += "\n\n---\n\n" + attachment
    return [
        Message(role="user", content=content),
    ]


# ---------------------------------------------------------------------------
# 压缩后恢复状态
# ---------------------------------------------------------------------------

# 追加到摘要 user 消息的恢复附件限制。compact 会清空工作对话；
# 没有这些快照，模型会忘记刚读过哪些文件、正在执行哪个 skill 的 SOP。
RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
RECOVERY_SKILLS_BUDGET = 25_000
RECOVERY_TOKENS_PER_SKILL = 5_000
_RECOVERY_CHARS_PER_TOKEN = 3.5


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: float


@dataclass
class SkillInvocationRecord:
    name: str
    body: str
    timestamp: float


class RecoveryState:
    """能在 Layer 2 压缩中存活下来的 per-agent 快照。

    记录 ReadFile 返回的字节内容，以及各个 skill 被调用时附带的 SOP 正文。
    这些记录会被重新附加到摘要的 user 消息上，这样即便对话记录被压缩清空，
    模型仍然保有可用的工作上下文。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileReadRecord] = {}
        self._skills: dict[str, SkillInvocationRecord] = {}

    def record_file_read(self, path: str, content: str) -> None:
        if not path:
            return
        with self._lock:
            self._files[path] = FileReadRecord(
                path=path, content=content, timestamp=time.time()
            )

    def record_skill_invocation(self, name: str, body: str) -> None:
        if not name:
            return
        with self._lock:
            self._skills[name] = SkillInvocationRecord(
                name=name, body=body, timestamp=time.time()
            )

    def snapshot_files(self, limit: int) -> list[FileReadRecord]:
        with self._lock:
            records = list(self._files.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if limit > 0:
            records = records[:limit]
        return records

    def snapshot_skills(self) -> list[SkillInvocationRecord]:
        with self._lock:
            records = list(self._skills.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records


def _approx_tokens(s: str) -> int:
    if not s:
        return 0
    return int(len(s) / _RECOVERY_CHARS_PER_TOKEN)


def _truncate_by_tokens(s: str, token_budget: int) -> str:
    if token_budget <= 0 or not s:
        return s
    if _approx_tokens(s) <= token_budget:
        return s
    max_chars = int(token_budget * _RECOVERY_CHARS_PER_TOKEN)
    if max_chars <= 0 or max_chars >= len(s):
        return s
    return s[:max_chars] + "\n… (内容已截断)"


def _first_line(s: str) -> str:
    for line in s.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_recovery_attachment(
    state: RecoveryState | None,
    tool_schemas: list[Mapping[str, Any]] | None,
) -> str:
    """渲染压缩后附件的四个小节。

    没有任何值得附加的内容时返回 ""，让调用方保持摘要消息干净。
    `tool_schemas` 应当是 agent 在下一次请求中将要发送的 schema —— 这里用其中的
    名称和描述来提醒模型当前都接入了哪些工具。
    """
    sections: list[str] = []

    if state is not None:
        files = state.snapshot_files(RECOVERY_FILE_LIMIT)
        if files:
            buf = ["## 最近读过的文件\n",
                   "以下快照是文件读取工具上次返回的内容。如需当前字节请重新读取。\n"]
            for rec in files:
                content = _truncate_by_tokens(rec.content, RECOVERY_TOKENS_PER_FILE)
                ts = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(rec.timestamp)
                )
                buf.append(f"### {rec.path}  (read {ts})\n")
                buf.append("```\n")
                buf.append(content)
                if not content.endswith("\n"):
                    buf.append("\n")
                buf.append("```\n")
            sections.append("".join(buf))

        skills = state.snapshot_skills()
        if skills:
            buf = ["## 已激活的技能\n",
                   "下列技能在本会话中被调用过，其触发条件仍然适用。\n"]
            used = 0
            emitted = False
            for sk in skills:
                body = _truncate_by_tokens(sk.body, RECOVERY_TOKENS_PER_SKILL)
                tokens = _approx_tokens(body) + _approx_tokens(sk.name) + 8
                if used + tokens > RECOVERY_SKILLS_BUDGET:
                    break
                used += tokens
                buf.append(f"### {sk.name}\n\n{body}\n")
                emitted = True
            if emitted:
                sections.append("".join(buf))

    if tool_schemas:
        buf = ["## 可用工具\n",
               "你仍然可以调用以下工具，需要时直接发起调用即可：\n"]
        for t in tool_schemas:
            name = t.get("name") if isinstance(t, Mapping) else None
            if not name:
                continue
            desc = t.get("description", "") if isinstance(t, Mapping) else ""
            desc = _first_line(desc or "")
            if desc:
                buf.append(f"- {name} — {desc}\n")
            else:
                buf.append(f"- {name}\n")
        sections.append("".join(buf))

    if not sections:
        return ""

    sections.append(
        "## 提示\n\n以上恢复的上下文是重建的。若需要原文代码、错误信息或用户原话，"
        "请用文件读取工具重新读取，不要根据摘要猜测细节。\n"
    )
    return "\n".join(sections)


def _group_messages_by_turn(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages:
        current.append(msg)
        if msg.role == "assistant" and not msg.tool_uses:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _message_tokens(msg: Message) -> int:
    """估算单条消息的 token 数，复用共享的字符数启发式算法。"""
    return estimate_tokens([msg])


def _compute_keep_start_index(messages: list[Message]) -> int:
    """决定压缩时尾部要原样保留多少条消息。

    从尾部向头部遍历 `messages`，逐条累加 token 估算值。只要还有任一保底条件
    未满足——累计 token 尚未达到 KEEP_RECENT_TOKENS，或保留的消息数仍少于
    MIN_KEEP_MESSAGES——当前消息就会被纳入保留窗口；但一旦纳入下一条消息会使
    保留总量超过 KEEP_MAX_TOKENS，遍历立即停止（这样单条超大的尾部消息就不会把
    整个 history 都拖进窗口）。

    返回第一条被保留消息的下标（keepStartIndex）。原始遍历结束后，必要时会把这个
    下标往前挪，确保被保留的 tool_result 不会和它对应的 tool_use 被拆散——
    参见 `_align_keep_start_to_tool_pair`。
    """
    n = len(messages)
    if n == 0:
        return 0

    kept_tokens = 0
    kept_count = 0
    keep_start = n  # 尚未保留任何消息

    for i in range(n - 1, -1, -1):
        tok = _message_tokens(messages[i])

        # 在已经保留了至少一条消息的前提下，如果纳入当前消息会突破硬上限则停止
        # （但绝不拒绝保留最后一条消息，即使它单独就超限）。
        if kept_count > 0 and kept_tokens + tok > KEEP_MAX_TOKENS:
            break

        kept_tokens += tok
        kept_count += 1
        keep_start = i

        # 保底条件已满足（token 下限或消息条数下限达到其一）：
        # 近期原文保留足够了，停止回溯。
        if kept_tokens >= KEEP_RECENT_TOKENS or kept_count >= MIN_KEEP_MESSAGES:
            break

    return _align_keep_start_to_tool_pair(messages, keep_start)


def _align_keep_start_to_tool_pair(messages: list[Message], keep_start: int) -> int:
    """把 keep_start 往前挪，确保我们绝不会保留一个孤立的 tool_result。

    携带 tool_results 的 user 消息，会和它前面那条发起对应 tool_uses 的 assistant
    消息配成一对。如果 keep_start 正好落在这样一条 user 消息上，就把它往前回退到
    （至少）配对的那条 assistant 消息，让 tool_use 与 tool_result 的配对关系保持完整。
    宁可多保留一对，也不要只保留半对（一个模型无法归属到任何调用的悬空 tool_result）。
    """
    while 0 < keep_start < len(messages):
        msg = messages[keep_start]
        if msg.role == "user" and msg.tool_results:
            prev = messages[keep_start - 1]
            if prev.role == "assistant" and prev.tool_uses:
                keep_start -= 1
                continue
        break
    return keep_start


def _prefix_too_small_to_compact(prefix: list[Message]) -> bool:
    """当摘要 `prefix` 能回收的空间太少、不值得做时返回 True。"""
    if not prefix:
        return True
    return estimate_tokens(prefix) < MIN_SUMMARIZE_PREFIX_TOKENS


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


@dataclass
class CompactCircuitBreaker:
    max_failures: int = 3
    consecutive_failures: int = field(default=0, init=False)

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0


    def is_open(self) -> bool:
        return self.consecutive_failures >= self.max_failures


# ---------------------------------------------------------------------------
# UsageAnchor — 真实 API 用量锚点（独立类型）
# ---------------------------------------------------------------------------


@dataclass
class UsageAnchor:
    """记录上一次真实 API 用量和当时的对话长度。

    baseline_tokens 是 input + cache_read + cache_creation + output 的合计值；
    anchor_count 是记录该数值时的 conversation.history 长度。锚点之后新增的消息
    没有真实用量数据，仅做字符估算。has_usage 为 False 时表示尚未收到任何 API
    用量报告（冷启动），此时退化为对整个 history 做字符估算。
    """

    baseline_tokens: int = 0
    anchor_count: int = 0
    has_usage: bool = False

    @staticmethod
    def from_api_usage(
        input_tokens: int,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
        msg_count: int = 0,
    ) -> UsageAnchor:
        """根据一次 API 响应构造锚点。"""
        return UsageAnchor(
            baseline_tokens=input_tokens + cache_read + cache_creation + output_tokens,
            anchor_count=msg_count,
            has_usage=True,
        )


# ---------------------------------------------------------------------------
# Auto-compact 编排器
# ---------------------------------------------------------------------------

async def auto_compact(
    conversation: ConversationManager,
    client: Any,
    context_window: int,
    session_dir: Path,
    protocol: str = "anthropic",
    manual: bool = False,
    breaker: CompactCircuitBreaker | None = None,
    recovery: RecoveryState | None = None,
    tool_schemas: list[Mapping[str, Any]] | None = None,
    transcript_path: str = "",
) -> CompactEvent | str | None:
    # 以真实 API 用量为锚点做阈值判断：current_tokens() 返回上次计费基准
    # （input + cache_read + cache_creation + output）加上锚点之后新增消息的
    # 字符估算。冷启动或刚压缩清空锚点时，退化为对整个 history 做字符估算。
    current = conversation.current_tokens()

    if manual:
        # 手动压缩（/compact）：直接走压缩流程，不检查阈值
        pass
    else:
        # 双阈值判断：
        # 1) 软触发线（auto margin 13K）：低于此线不需要压缩
        soft_threshold = compute_compact_threshold(context_window, manual=False)
        if current < soft_threshold:
            return None

        # 2) 硬触发线（manual margin 3K）：超过此线强制压缩，绕过熔断器，
        #    因为上下文已经过于接近窗口上限，不能冒跳过的风险
        hard_threshold = compute_compact_threshold(context_window, manual=True)
        if current >= hard_threshold:
            # 强制压缩路径：不检查熔断器
            pass
        else:
            # 处于软硬阈值之间：走正常的熔断器保护逻辑
            if breaker is not None and breaker.is_open():
                return "自动压缩已熔断（连续失败 3 次），请手动处理或使用 /compact"

    before_tokens = current

    # 历史里的工具结果在入历史时已按预算处理为终态，history 就是实际
    # 发送量，直接基于它计算 keep_start 和构建摘要。
    effective_history = conversation.history

    # 决定保留多少尾部消息原文。只有前缀 messages[:keep_start] 会被摘要；
    # messages[keep_start:] 原样保留，让模型看到近期原文而非靠有损摘要复述。
    keep_start = _compute_keep_start_index(effective_history)
    to_summarize = effective_history[:keep_start]
    keep_tail = effective_history[keep_start:]

    # 待摘要的前缀太小时退化为不压缩——要么全部消息都落在保留窗口内
    # （keep_start <= 0），要么摘要回收的 token 还不够摘要本身的开销。
    if keep_start <= 0 or _prefix_too_small_to_compact(to_summarize):
        return None

    messages_for_summary = build_messages(list(to_summarize), protocol)

    summary_messages: list[dict[str, Any]] = [
        {"role": "user", "content": SUMMARY_PROMPT},
    ]
    summary_messages.extend(messages_for_summary)
    summary_messages.append(
        {"role": "user", "content": "Please provide your summary of the conversation above now. REMINDER: Do NOT call any tools — respond with plain text only."}
    )

    summary_conv = ConversationManager()
    summary_conv.history = [
        Message(role="user", content=SUMMARY_PROMPT),
    ]
    # 只摘要前缀；保留的尾部在下面重建时原样拼回。
    for msg in to_summarize:
        summary_conv.history.append(msg)
    summary_conv.history.append(
        Message(role="user", content="Please provide your summary of the conversation above now. REMINDER: Do NOT call any tools — respond with plain text only.")
    )

    max_retries = 3
    llm_output: str | None = None

    for attempt in range(max_retries):
        try:
            from mewcode.tools.base import StreamEnd, StreamEvent, TextDelta

            collected_text = ""
            async for event in client.stream(summary_conv, system=SUMMARY_PROMPT, tools=tool_schemas):
                if isinstance(event, TextDelta):
                    collected_text += event.text
                elif isinstance(event, StreamEnd):
                    pass
            llm_output = collected_text
            break

        except Exception as e:
            err_msg = str(e).lower()
            if "prompt" in err_msg and "long" in err_msg or "too many" in err_msg:
                groups = _group_messages_by_turn(summary_conv.history[1:-1])
                drop_count = max(1, len(groups) // 5)
                remaining = groups[drop_count:]
                summary_conv.history = (
                    [summary_conv.history[0]]
                    + [m for g in remaining for m in g]
                    + [summary_conv.history[-1]]
                )
                continue
            if breaker is not None:
                breaker.record_failure()
            return f"摘要生成失败: {e}"

    if llm_output is None:
        if breaker is not None:
            breaker.record_failure()
        return "摘要生成失败：多次重试后仍超出上下文限制"

    summary = extract_summary(llm_output)
    attachment = build_recovery_attachment(recovery, tool_schemas)
    # 重建 = 摘要(user) + 尾部原文。
    new_messages = build_compact_messages(
        summary,
        attachment=attachment,
        has_keep_tail=bool(keep_tail),
        transcript_path=transcript_path,
    )
    new_messages = new_messages + list(keep_tail)

    # replace_history 替换为重建后的对话并将用量锚点清零
    # （baseline_tokens / anchor_count / last_input_tokens），这是必须的：
    # 旧的 anchor_count 对应压缩前的消息列表，现在已无意义，
    # 不清零会导致 current_tokens() 对增量的估算出错。
    # 下一次 API 响应会基于重建后的 history 重新锚定。
    conversation.replace_history(new_messages)
    cleanup_tool_results(session_dir)

    if breaker is not None:
        breaker.record_success()

    # 将结构化的 boundary（摘要 + 保留的尾部原文）交给 session 层，
    # 由它持久化为一条 compact_boundary 记录。keep tail 就是拼回重建 history 的那段。
    return CompactEvent(
        before_tokens=before_tokens,
        boundary=CompactBoundary(summary=summary, keep=list(keep_tail)),
    )
