# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
"""针对各 provider 序列化构建器的单元测试。

会话层与具体 provider 无关；序列化逻辑位于 mewcode.serialization。
这些测试用于锁定各种线上传输格式（wire format），更关键的是锁定
Extended Thinking 的往返（round-trip）契约：带 tool-use 的这一轮必须把它
带签名的 thinking block 一并回传给 API（否则 Anthropic 会返回 400）。
"""
from __future__ import annotations

from mewcode.conversation import (
    ConversationManager,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from mewcode.serialization import (
    build_anthropic_messages,
    build_chat_completion_messages,
    build_messages,
    build_openai_input,
)


def test_anthropic_preserves_signed_thinking_at_head():
    conv = ConversationManager()
    conv.add_assistant_message(
        "answer",
        tool_uses=[ToolUseBlock(tool_use_id="tu-1", tool_name="Bash", arguments={"command": "ls"})],
        thinking_blocks=[ThinkingBlock(thinking="let me think", signature="sig-1")],
    )
    msgs = build_anthropic_messages(conv.get_messages())
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert content[0]["type"] == "thinking"
    assert content[0]["signature"] == "sig-1"
    assert content[-1]["type"] == "tool_use"


def test_anthropic_tool_results_become_user_blocks():
    conv = ConversationManager()
    conv.add_tool_results_message([ToolResultBlock(tool_use_id="tu-1", content="out", is_error=False)])
    msgs = build_anthropic_messages(conv.get_messages())
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"][0]["type"] == "tool_result"
    assert msgs[0]["content"][0]["tool_use_id"] == "tu-1"


def test_anthropic_merges_system_reminder_into_prev_user():
    conv = ConversationManager()
    conv.add_user_message("hello")
    conv.add_system_reminder("note")
    msgs = build_anthropic_messages(conv.get_messages())
    assert len(msgs) == 1
    assert "hello" in msgs[0]["content"]
    assert "system-reminder" in msgs[0]["content"]


def test_openai_input_tool_use_as_function_call():
    conv = ConversationManager()
    conv.add_assistant_message(
        "text",
        tool_uses=[ToolUseBlock(tool_use_id="tu-1", tool_name="Bash", arguments={"command": "ls"})],
    )
    msgs = build_openai_input(conv.get_messages())
    assert len(msgs) == 2  # 文本消息 + function_call
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["type"] == "function_call"
    assert msgs[1]["name"] == "Bash"


def test_openai_input_tool_results_as_function_call_output():
    conv = ConversationManager()
    conv.add_tool_results_message([ToolResultBlock(tool_use_id="tu-1", content="out")])
    msgs = build_openai_input(conv.get_messages())
    assert msgs[0]["type"] == "function_call_output"
    assert msgs[0]["output"] == "out"


def test_chat_completion_uses_tool_calls_with_reasoning_content():
    conv = ConversationManager()
    conv.add_assistant_message(
        "text",
        tool_uses=[ToolUseBlock(tool_use_id="tu-1", tool_name="Bash", arguments={"command": "ls"})],
        thinking_blocks=[ThinkingBlock(thinking="let me think", signature="sig")],
    )
    msgs = build_chat_completion_messages(conv.get_messages())
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["tool_calls"][0]["function"]["name"] == "Bash"
    # thinking blocks 作为 reasoning_content 回传（DeepSeek/小米等 provider 要求）
    assert msgs[0]["reasoning_content"] == "let me think"


def test_chat_completion_no_reasoning_when_no_thinking():
    conv = ConversationManager()
    conv.add_assistant_message(
        "text",
        tool_uses=[ToolUseBlock(tool_use_id="tu-1", tool_name="Bash", arguments={"command": "ls"})],
    )
    msgs = build_chat_completion_messages(conv.get_messages())
    assert "reasoning_content" not in msgs[0]


def test_openai_input_includes_reasoning_items():
    conv = ConversationManager()
    conv.add_assistant_message(
        "text",
        tool_uses=[ToolUseBlock(tool_use_id="tu-1", tool_name="Bash", arguments={"command": "ls"})],
        thinking_blocks=[ThinkingBlock(thinking="reasoning here", signature="rs-001")],
    )
    msgs = build_openai_input(conv.get_messages())
    # 第一个 item 应该是 reasoning
    assert msgs[0]["type"] == "reasoning"
    assert msgs[0]["id"] == "rs-001"
    assert msgs[0]["summary"][0]["text"] == "reasoning here"


def test_build_messages_dispatch_by_protocol():
    conv = ConversationManager()
    conv.add_user_message("hi")
    msgs = conv.get_messages()
    assert build_messages(msgs, "anthropic") == build_anthropic_messages(msgs)
    assert build_messages(msgs, "openai") == build_openai_input(msgs)
    assert build_messages(msgs, "openai-compat") == build_chat_completion_messages(msgs)
