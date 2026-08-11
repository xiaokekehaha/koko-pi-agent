# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from mewcode.conversation import Message, ToolResultBlock, ToolUseBlock
from mewcode.conversation_pairing import INTERRUPTED_TOOL_RESULT, ensure_tool_pairing


def assistant_with_tool(tool_id: str) -> Message:
    return Message(
        role="assistant",
        content="let me check",
        tool_uses=[ToolUseBlock(tool_use_id=tool_id, tool_name="ReadFile", arguments={})],
    )


def result_for(tool_id: str, content: str) -> Message:
    return Message(
        role="user",
        content="",
        tool_results=[ToolResultBlock(tool_use_id=tool_id, content=content, is_error=False)],
    )


def test_paired_history_is_untouched() -> None:
    got = ensure_tool_pairing(
        [Message(role="user", content="hi"), assistant_with_tool("t1"), result_for("t1", "content")]
    )
    assert len(got) == 3
    assert got[2].tool_results[0].content == "content"


def test_dangling_tool_use_is_filled() -> None:
    got = ensure_tool_pairing([Message(role="user", content="hi"), assistant_with_tool("t1")])
    assert len(got) == 3
    filled = got[2].tool_results[0]
    assert filled.tool_use_id == "t1"
    assert filled.is_error is True
    assert filled.content == INTERRUPTED_TOOL_RESULT


def test_orphan_result_is_dropped() -> None:
    got = ensure_tool_pairing(
        [Message(role="user", content="hi"), result_for("ghost", "leftover"), Message(role="assistant", content="ok")]
    )
    assert len(got) == 2
    for m in got:
        for tr in m.tool_results or []:
            assert tr.tool_use_id != "ghost"


def test_no_duplicate_fill() -> None:
    got = ensure_tool_pairing([assistant_with_tool("t1"), Message(role="assistant", content="still going")])
    count = sum(1 for m in got for tr in (m.tool_results or []) if tr.tool_use_id == "t1")
    assert count == 1


def test_input_is_not_mutated() -> None:
    original = [assistant_with_tool("t1")]
    ensure_tool_pairing(original)
    assert len(original) == 1
    assert not original[0].tool_results
