# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from koko_pi_agent.context.manager import (
    AGGREGATE_CHAR_LIMIT,
    KEEP_MAX_TOKENS,
    KEEP_RECENT_TOKENS,
    MIN_KEEP_MESSAGES,
    PERSISTED_TAG,
    CompactCircuitBreaker,
    _align_keep_start_to_tool_pair,
    _compute_keep_start_index,
    apply_tool_result_budget,
    auto_compact,
    build_compact_messages,
    cleanup_tool_results,
    compute_compact_threshold,
    ensure_session_dir,
    extract_summary,
    is_spill_readback,
    make_persisted_preview,
    persist_tool_result,
)
from koko_pi_agent.conversation import (
    _CHARS_PER_TOKEN,
    ConversationManager,
    Message,
    ToolResultBlock,
    ToolUseBlock,
    estimate_tokens,
)

# ---------------------------------------------------------------------------
# persist_tool_result
# ---------------------------------------------------------------------------

class TestPersistToolResult:
    def test_writes_file(self, tmp_path: Path) -> None:
        fp = persist_tool_result("toolu_001", "hello world", tmp_path)
        assert fp.exists()
        assert fp.read_text() == "hello world"

    def test_idempotent(self, tmp_path: Path) -> None:
        persist_tool_result("toolu_002", "first", tmp_path)
        persist_tool_result("toolu_002", "second", tmp_path)
        fp = tmp_path / "toolu_002.txt"
        assert fp.read_text() == "first"

# ---------------------------------------------------------------------------
# make_persisted_preview
# ---------------------------------------------------------------------------

class TestMakePersistedPreview:
    def test_contains_tag_and_path(self, tmp_path: Path) -> None:
        content = "x" * 10_000
        preview = make_persisted_preview(content, tmp_path / "test.txt")
        assert preview.startswith(PERSISTED_TAG)
        assert "test.txt" in preview
        assert "</persisted-output>" in preview

    def test_preview_truncated(self, tmp_path: Path) -> None:
        content = "a" * 5_000
        preview = make_persisted_preview(content, tmp_path / "test.txt")
        lines = preview.split("\n")
        preview_line = [l for l in lines if l.startswith("aaa")]
        assert len(preview_line) == 1
        assert len(preview_line[0]) == 2_000

# ---------------------------------------------------------------------------
# apply_tool_result_budget
# ---------------------------------------------------------------------------

class TestApplyToolResultBudget:
    def _batch(self, *sizes: int) -> list[ToolResultBlock]:
        return [
            ToolResultBlock(tool_use_id=f"t{i + 1}", content="x" * n)
            for i, n in enumerate(sizes)
        ]

    def test_under_limit_untouched(self, tmp_path: Path) -> None:
        batch = self._batch(40_000, 40_000)

        apply_tool_result_budget(batch, tmp_path)

        assert batch[0].content == "x" * 40_000
        assert batch[1].content == "x" * 40_000

    def test_aggregate_spills_largest_first(self, tmp_path: Path) -> None:
        # 5 条合计 225K+1，只需溢写最大的 t3 即可回到限额内
        batch = self._batch(45_000, 45_000, 45_001, 45_000, 45_000)

        apply_tool_result_budget(batch, tmp_path)

        total = sum(len(tr.content) for tr in batch)
        assert total <= AGGREGATE_CHAR_LIMIT
        replaced = [tr for tr in batch if tr.content.startswith(PERSISTED_TAG)]
        assert len(replaced) == 1
        assert batch[2].content.startswith(PERSISTED_TAG)
        # 溢写文件保存了完整内容
        assert (tmp_path / "t3.txt").read_text() == "x" * 45_001

    def test_exempt_skipped(self, tmp_path: Path) -> None:
        batch = self._batch(45_000, 45_000, 45_001, 45_000, 45_000)

        apply_tool_result_budget(batch, tmp_path, {"t3"})

        assert not batch[2].content.startswith(PERSISTED_TAG)
        total = sum(len(tr.content) for tr in batch)
        assert total <= AGGREGATE_CHAR_LIMIT

    def test_all_exempt_accepts_overage(self, tmp_path: Path) -> None:
        batch = self._batch(105_000, 105_000)

        apply_tool_result_budget(batch, tmp_path, {"t1", "t2"})

        assert batch[0].content == "x" * 105_000
        assert batch[1].content == "x" * 105_000

    def test_deterministic_output(self, tmp_path: Path) -> None:
        batch1 = self._batch(45_000, 45_000, 45_001, 45_000, 45_000)
        batch2 = self._batch(45_000, 45_000, 45_001, 45_000, 45_000)

        apply_tool_result_budget(batch1, tmp_path)
        apply_tool_result_budget(batch2, tmp_path)

        for a, b in zip(batch1, batch2):
            assert a.content == b.content

    def test_idempotent_on_processed_batch(self, tmp_path: Path) -> None:
        batch = self._batch(45_000, 45_000, 45_001, 45_000, 45_000)
        apply_tool_result_budget(batch, tmp_path)
        snapshot = [tr.content for tr in batch]

        apply_tool_result_budget(batch, tmp_path)

        assert [tr.content for tr in batch] == snapshot

# ---------------------------------------------------------------------------
# is_spill_readback
# ---------------------------------------------------------------------------

class TestIsSpillReadback:
    def test_readfile_inside_spill_dir(self, tmp_path: Path) -> None:
        inside = str(tmp_path / "toolu_abc.txt")
        assert is_spill_readback("ReadFile", {"file_path": inside}, tmp_path)

    def test_readfile_outside(self, tmp_path: Path) -> None:
        assert not is_spill_readback(
            "ReadFile", {"file_path": str(tmp_path.parent / "main.py")}, tmp_path
        )

    def test_other_tool(self, tmp_path: Path) -> None:
        inside = str(tmp_path / "toolu_abc.txt")
        assert not is_spill_readback("Bash", {"file_path": inside}, tmp_path)

    def test_missing_path(self, tmp_path: Path) -> None:
        assert not is_spill_readback("ReadFile", {}, tmp_path)

# ---------------------------------------------------------------------------
# compute_compact_threshold
# ---------------------------------------------------------------------------

class TestComputeCompactThreshold:
    def test_auto_threshold(self) -> None:
        assert compute_compact_threshold(200_000) == 167_000

    def test_manual_threshold(self) -> None:
        assert compute_compact_threshold(200_000, manual=True) == 177_000

    def test_smaller_window(self) -> None:
        assert compute_compact_threshold(128_000) == 95_000

# ---------------------------------------------------------------------------
# extract_summary
# ---------------------------------------------------------------------------

class TestExtractSummary:
    def test_extracts_between_tags(self) -> None:
        output = "<analysis>blah</analysis>\n<summary>\nthe summary\n</summary>"
        assert extract_summary(output) == "the summary"

    def test_no_tags_returns_full(self) -> None:
        output = "no tags here"
        assert extract_summary(output) == output

    def test_only_summary_tag(self) -> None:
        output = "<summary>just this</summary>"
        assert extract_summary(output) == "just this"

# ---------------------------------------------------------------------------
# CompactCircuitBreaker
# ---------------------------------------------------------------------------

class TestCompactCircuitBreaker:
    def test_starts_closed(self) -> None:
        breaker = CompactCircuitBreaker()
        assert not breaker.is_open()

    def test_opens_after_max_failures(self) -> None:
        breaker = CompactCircuitBreaker(max_failures=3)
        breaker.record_failure()
        breaker.record_failure()
        assert not breaker.is_open()
        breaker.record_failure()
        assert breaker.is_open()

    def test_success_resets(self) -> None:
        breaker = CompactCircuitBreaker(max_failures=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert not breaker.is_open()
        breaker.record_failure()
        assert not breaker.is_open()

# ---------------------------------------------------------------------------
# build_compact_messages
# ---------------------------------------------------------------------------

class TestBuildCompactMessages:
    def test_basic_structure(self) -> None:
        msgs = build_compact_messages("the summary")
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert "the summary" in msgs[0].content
        assert "早期对话的摘要" in msgs[0].content

    def test_has_keep_tail(self) -> None:
        msgs = build_compact_messages("the summary", has_keep_tail=True)
        assert "近期消息已原样保留" in msgs[0].content

    def test_transcript_path(self) -> None:
        msgs = build_compact_messages("the summary", transcript_path="/tmp/session.jsonl")
        assert "/tmp/session.jsonl" in msgs[0].content
        assert "ReadFile" in msgs[0].content

# ---------------------------------------------------------------------------
# 会话目录管理
# ---------------------------------------------------------------------------

class TestSessionDir:
    def test_ensure_creates_dir(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(str(tmp_path))
        assert session_dir.exists()
        assert session_dir.is_dir()

    def test_cleanup(self, tmp_path: Path) -> None:
        session_dir = ensure_session_dir(str(tmp_path))
        (session_dir / "test.txt").write_text("data")
        assert len(list(session_dir.iterdir())) == 1

        cleanup_tool_results(session_dir)
        assert session_dir.exists()
        assert len(list(session_dir.iterdir())) == 0


# ---------------------------------------------------------------------------
# 真实用量锚点 + 增量估算（current_tokens）
# ---------------------------------------------------------------------------

class TestUsageAnchor:
    def test_cold_start_falls_back_to_char_estimate(self) -> None:
        """尚无锚点时：current_tokens 按字符数对整段历史进行估算。"""
        conv = ConversationManager()
        conv.add_user_message("x" * 350)
        assert conv.baseline_tokens == 0
        # 350 个字符 / 3.5 == 100 个 token，与对历史调用 estimate_tokens 的结果一致。
        assert conv.current_tokens() == estimate_tokens(conv.history) == 100

    def test_anchor_aggregates_all_usage_components(self) -> None:
        """baseline = input + cache_read + cache_creation + output。"""
        conv = ConversationManager()
        conv.add_user_message("hi")
        conv.record_usage_anchor(
            input_tokens=1000,
            output_tokens=200,
            cache_read=5000,
            cache_creation=300,
        )
        assert conv.baseline_tokens == 1000 + 5000 + 300 + 200
        assert conv.anchor_count == len(conv.history)
        # last_input_tokens 与之保持同步，以兼容旧的读取方。
        assert conv.last_input_tokens == conv.baseline_tokens

    def test_current_tokens_is_baseline_plus_increment(self) -> None:
        """存在锚点时，只对锚点之后追加的消息进行估算。"""
        conv = ConversationManager()
        conv.add_user_message("first turn")
        conv.record_usage_anchor(input_tokens=8000, output_tokens=100)
        baseline = conv.baseline_tokens  # 8100

        # 还没有新消息 -> 正好等于基准值（不会重新估算历史）。
        assert conv.current_tokens() == baseline

        # 追加一条 700 个字符的 tool result -> 在基准之上再加 200 个估算 token。
        conv.add_tool_results_message(
            [ToolResultBlock(tool_use_id="t1", content="y" * 700)]
        )
        assert conv.current_tokens() == baseline + 200
        # 锚点之前的消息通过基准值采信，不再重复计数。
        increment = estimate_tokens(conv.history[conv.anchor_count:])
        assert increment == 200

    def test_anchor_beats_char_estimate_after_cache_hit(self) -> None:
        """命中缓存后，真实 input（很小）所对应的锚点会低于同一段大历史按字符的估算值，
        这样就不会把缓存命中的 token 重复多算。"""
        conv = ConversationManager()
        conv.add_user_message("z" * 35000)  # 按字符估算会得到 10000 个 token
        # 缓存命中：prompt 的大部分是从缓存读取的，真实 input 很小。
        conv.record_usage_anchor(
            input_tokens=200, output_tokens=50, cache_read=9000
        )
        # 锚点反映真实的 9250，而不是被夸大的按字符估算值。
        assert conv.current_tokens() == 9250
        assert conv.current_tokens() < estimate_tokens(conv.history)

    def test_replace_history_resets_anchor(self) -> None:
        """压缩会清除锚点，使下一次检查从冷启动开始。"""
        conv = ConversationManager()
        conv.add_user_message("old turn")
        conv.record_usage_anchor(input_tokens=9000, output_tokens=100)
        assert conv.baseline_tokens > 0

        conv.replace_history([Message(role="user", content="summary " + "s" * 70)])
        assert conv.baseline_tokens == 0
        assert conv.anchor_count == 0
        assert conv.last_input_tokens == 0
        # 此时回退到按字符估算已被摘要后的历史。
        assert conv.current_tokens() == estimate_tokens(conv.history)


class TestEstimateTokens:
    def test_empty(self) -> None:
        assert estimate_tokens([]) == 0

    def test_counts_text_thinking_tools_and_results(self) -> None:
        from koko_pi_agent.conversation import ThinkingBlock

        msgs = [
            Message(role="user", content="a" * 35),
            Message(
                role="assistant",
                content="b" * 35,
                thinking_blocks=[ThinkingBlock(thinking="c" * 35, signature="sig")],
                tool_uses=[ToolUseBlock("id", "Tool", {"k": "v"})],
            ),
            Message(
                role="user",
                content="",
                tool_results=[ToolResultBlock(tool_use_id="id", content="d" * 35)],
            ),
        ]
        # text(35) + text(35)+thinking(35)+工具名/参数 + result(35)
        est = estimate_tokens(msgs)
        # 下界：仅这四个 35 字符的块就是 140 个字符 / 3.5 = 40。
        assert est >= int(140 / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# 流式用量 -> 锚点流水线（cache 字段透传）
# ---------------------------------------------------------------------------

class TestStreamUsageCacheFields:
    def test_stream_end_carries_cache_fields(self) -> None:
        from koko_pi_agent.tools.base import StreamEnd

        end = StreamEnd(
            stop_reason="end_turn",
            input_tokens=1,
            output_tokens=2,
            cache_read=3,
            cache_creation=4,
        )
        assert end.cache_read == 3 and end.cache_creation == 4

    def test_collector_propagates_cache_fields_into_response(self) -> None:
        import asyncio

        from koko_pi_agent.agent import StreamCollector
        from koko_pi_agent.tools.base import StreamEnd

        async def _stream():
            yield StreamEnd(
                stop_reason="end_turn",
                input_tokens=1000,
                output_tokens=200,
                cache_read=5000,
                cache_creation=300,
            )

        async def _run():
            collector = StreamCollector()
            async for _ in collector.consume(_stream()):
                pass
            return collector.response

        resp = asyncio.run(_run())
        assert resp.cache_read == 5000
        assert resp.cache_creation == 300

        # 把这个 response 喂给锚点，能复现出完整的基准值。
        conv = ConversationManager()
        conv.record_usage_anchor(
            resp.input_tokens, resp.output_tokens,
            resp.cache_read, resp.cache_creation,
        )
        assert conv.baseline_tokens == 1000 + 5000 + 300 + 200


# ---------------------------------------------------------------------------
# 保留最近原文的窗口：keepStartIndex 计算 + 工具配对
# ---------------------------------------------------------------------------

# _CHARS_PER_TOKEN == 3.5，所以一条 N*3.5 个字符的消息估算约为 N 个 token。
def _user(text_tokens: int) -> Message:
    return Message(role="user", content="u" * int(text_tokens * _CHARS_PER_TOKEN))


def _assistant(text_tokens: int) -> Message:
    return Message(role="assistant", content="a" * int(text_tokens * _CHARS_PER_TOKEN))


class TestComputeKeepStartIndex:
    def test_empty_history(self) -> None:
        assert _compute_keep_start_index([]) == 0

    def test_stops_at_token_floor(self) -> None:
        # 10 条消息，每条约 4000 个 token。从尾部往前走，走到第 3 条时
        # 累计达到约 12000 >= KEEP_RECENT_TOKENS（10000）便停止 -> 保留最后 3 条。
        msgs = [_user(4000) for _ in range(10)]
        keep_start = _compute_keep_start_index(msgs)
        kept = msgs[keep_start:]
        assert len(kept) == 3
        assert keep_start == 7
        assert estimate_tokens(kept) >= KEEP_RECENT_TOKENS

    def test_message_floor_when_tail_is_tiny(self) -> None:
        # 极小的消息永远达不到 token 下限，所以最终是保底的 MIN_KEEP_MESSAGES
        # 条数停止了遍历。
        msgs = [_user(50) for _ in range(20)]
        keep_start = _compute_keep_start_index(msgs)
        assert len(msgs[keep_start:]) == MIN_KEEP_MESSAGES
        assert keep_start == 20 - MIN_KEEP_MESSAGES

    def test_max_cap_stops_swallowing_history(self) -> None:
        # 一条超大的尾部消息（> KEEP_MAX_TOKENS）会被保留（永远不会拒绝
        # 最后一条消息），但遍历会在把更早的消息纳入之前就停止。
        big = _user(KEEP_MAX_TOKENS // 1000 * 1000 + 5000)
        msgs = [_user(4000) for _ in range(6)] + [big]
        keep_start = _compute_keep_start_index(msgs)
        assert keep_start == len(msgs) - 1  # 只保留那条超大的尾部消息
        assert estimate_tokens(msgs[keep_start:]) > KEEP_MAX_TOKENS

    def test_short_history_keeps_everything(self) -> None:
        # 消息数少于 MIN_KEEP_MESSAGES -> keep_start 一直走到 0。
        msgs = [_user(50) for _ in range(3)]
        assert _compute_keep_start_index(msgs) == 0


class TestAlignKeepStartToToolPair:
    def test_orphan_tool_result_pulled_back_to_tool_use(self) -> None:
        # assistant(tool_use) 在 idx2，user(tool_result) 在 idx3。如果 keep_start
        # 落在 idx3，就会保留一个悬空的 tool_result -> 回退到 idx2。
        msgs = [
            _user(10),
            _assistant(10),
            Message(role="assistant", content="call",
                    tool_uses=[ToolUseBlock("t1", "ReadFile", {})]),
            Message(role="user", content="",
                    tool_results=[ToolResultBlock("t1", "data")]),
        ]
        assert _align_keep_start_to_tool_pair(msgs, 3) == 2

    def test_non_tool_boundary_untouched(self) -> None:
        msgs = [_user(10), _assistant(10), _user(10)]
        assert _align_keep_start_to_tool_pair(msgs, 2) == 2

    def test_pairing_preserved_via_compute(self) -> None:
        # 计算出的 keep_start 若会把一对 tool_use/tool_result 拆开，则会被纠正。
        msgs = [_user(4000) for _ in range(6)]
        # 让位于自然保留边界处的消息成为一个 tool_result，且其对应的
        # tool_use 正好紧挨在它前面。
        msgs[6:6] = []  # 空操作，仅为显式表达意图而保留
        msgs = [
            _user(4000), _user(4000), _user(4000), _user(4000),
            Message(role="assistant", content="call",
                    tool_uses=[ToolUseBlock("tx", "Grep", {})]),
            Message(role="user", content="",
                    tool_results=[ToolResultBlock("tx", "y" * (4000 * 3))]),
            _user(4000),
        ]
        keep_start = _compute_keep_start_index(msgs)
        kept = msgs[keep_start:]
        # 如果保留了某个 tool_result，那么它对应的 tool_use 也必须被保留（不留孤儿）。
        kept_result_ids = {
            tr.tool_use_id for m in kept for tr in m.tool_results
        }
        kept_use_ids = {
            tu.tool_use_id for m in kept for tu in m.tool_uses
        }
        assert kept_result_ids <= kept_use_ids


# ---------------------------------------------------------------------------
# auto_compact：原文保留最近消息 + 摘要只覆盖前缀 + 重置锚点
# ---------------------------------------------------------------------------

class _SummaryClient:
    """一个极简的流式客户端：返回固定的摘要，并记录下它被要求去摘要的那段历史。"""

    def __init__(self, summary_body: str = "PREFIX SUMMARY") -> None:
        self.summary_body = summary_body
        self.summarized_history: list[Message] | None = None

    async def stream(self, conversation, system="", tools=None):
        from koko_pi_agent.tools.base import StreamEnd, TextDelta

        # 快照记录交给摘要器的内容（不含编排器额外添加的开头 prompt
        # 以及结尾的"请生成摘要"指令）。
        self.summarized_history = list(conversation.history)
        yield TextDelta(text=f"<summary>{self.summary_body}</summary>")
        yield StreamEnd(stop_reason="end_turn", input_tokens=10, output_tokens=10)


def _make_long_conversation(n_tail: int = 6, tail_tokens: int = 4000) -> ConversationManager:
    conv = ConversationManager()
    # 值得做摘要的旧前缀（远高于 MIN_SUMMARIZE_PREFIX_TOKENS）。
    for i in range(8):
        conv.history.append(_user(3000))
        conv.history.append(_assistant(3000))
    # 一些可区分的、最近的尾部消息，我们将断言它们会原文保留下来。
    for i in range(n_tail):
        conv.history.append(
            Message(role="user", content=f"RECENT_{i}_" + "z" * int(tail_tokens * _CHARS_PER_TOKEN))
        )
    return conv


@pytest.mark.asyncio
class TestAutoCompactKeepRecent:
    async def test_recent_messages_kept_verbatim(self, tmp_path: Path) -> None:
        conv = _make_long_conversation()
        # 快照记录保留窗口选中了哪些尾部消息，让断言跟随算法本身，
        # 而不是依赖写死的数量。
        keep_start = _compute_keep_start_index(conv.history)
        kept_before = list(conv.history[keep_start:])
        assert kept_before, "fixture should keep a non-empty tail"

        client = _SummaryClient()
        # 钉一个很高的锚点，使自动压缩阈值被触发。
        conv.record_usage_anchor(input_tokens=200_000)

        result = await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
        )

        # 已完成压缩。
        from koko_pi_agent.context.manager import CompactEvent
        assert isinstance(result, CompactEvent)

        joined = "\n".join(m.content for m in conv.history)
        # 摘要存在……
        assert "PREFIX SUMMARY" in joined
        # ……并且保留下来的最近原文仍是逐字原样，没有被改写进摘要里。
        # 保留的尾部对象是同一批消息实例，被原样沿用了下来。
        for m in kept_before:
            assert m in conv.history

    async def test_summary_only_covers_prefix(self, tmp_path: Path) -> None:
        conv = _make_long_conversation()
        keep_start = _compute_keep_start_index(conv.history)
        kept_contents = {m.content for m in conv.history[keep_start:]}
        client = _SummaryClient()
        conv.record_usage_anchor(input_tokens=200_000)

        await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
        )

        # 喂给摘要器的历史绝不能包含任何被保留的尾部消息
        #（摘要只覆盖 messages[:keep_start]）。
        assert client.summarized_history is not None
        summarized_contents = {m.content for m in client.summarized_history}
        assert not (kept_contents & summarized_contents)

    async def test_tool_pair_not_split(self, tmp_path: Path) -> None:
        conv = ConversationManager()
        for i in range(8):
            conv.history.append(_user(3000))
            conv.history.append(_assistant(3000))
        # 最近的尾部以一对 tool_use/tool_result 结尾。
        conv.history.append(
            Message(role="assistant", content="calling",
                    tool_uses=[ToolUseBlock("tk", "Grep", {})])
        )
        conv.history.append(
            Message(role="user", content="",
                    tool_results=[ToolResultBlock("tk", "RESULT_DATA")])
        )
        conv.record_usage_anchor(input_tokens=200_000)
        client = _SummaryClient()

        await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
        )

        # 如果 tool_result 被保留下来，它对应的 tool_use 也必须一起保留。
        result_ids = {tr.tool_use_id for m in conv.history for tr in m.tool_results}
        use_ids = {tu.tool_use_id for m in conv.history for tu in m.tool_uses}
        assert result_ids <= use_ids

    async def test_anchor_reset_after_compact(self, tmp_path: Path) -> None:
        conv = _make_long_conversation()
        conv.record_usage_anchor(input_tokens=200_000)
        assert conv.baseline_tokens > 0 and conv.anchor_count > 0
        client = _SummaryClient()

        await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
        )

        # replace_history 必须已经把过期的锚点清零。
        assert conv.baseline_tokens == 0
        assert conv.anchor_count == 0
        assert conv.last_input_tokens == 0

    async def test_too_few_messages_degrades_to_no_compaction(
        self, tmp_path: Path
    ) -> None:
        conv = ConversationManager()
        for i in range(3):
            conv.history.append(
                Message(role="user", content=f"ONLY_{i}_" + "z" * 100)
            )
        before = list(conv.history)
        client = _SummaryClient()

        result = await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
            manual=True,
        )

        # 没有可摘要的内容 -> 降级处理：历史保持不变，不添加任何摘要。
        assert result is None
        assert conv.history == before
        assert client.summarized_history is None

    async def test_event_carries_boundary_summary_and_keep(
        self, tmp_path: Path
    ) -> None:
        # 返回的 CompactEvent 必须把一个结构化的 boundary（摘要 + 精确逐字
        # 保留的尾部）交给会话层，使其能持久化一条 compact_boundary 记录。
        conv = _make_long_conversation()
        keep_start = _compute_keep_start_index(conv.history)
        kept_before = list(conv.history[keep_start:])
        client = _SummaryClient()
        conv.record_usage_anchor(input_tokens=200_000)

        result = await auto_compact(
            conv, client, context_window=200_000, session_dir=tmp_path,
        )

        from koko_pi_agent.context.manager import CompactEvent

        assert isinstance(result, CompactEvent)
        assert result.boundary is not None
        assert result.boundary.summary == "PREFIX SUMMARY"
        # 保留的尾部与原样沿用下来的内容完全一致。
        assert result.boundary.keep == kept_before
