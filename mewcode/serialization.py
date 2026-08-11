# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import json
from typing import Any

from mewcode.conversation import Message

# 把 provider 无关的内部消息序列化成各家 API 的请求格式。
# 这一层属于「适配器」职责，对话层（ConversationManager）只管消息、不懂线上格式。


def build_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses or m.thinking_blocks:
            content: list[dict[str, Any]] = []
            for tb in m.thinking_blocks:
                content.append({
                    "type": "thinking",
                    "thinking": tb.thinking,
                    "signature": tb.signature,
                })
            if m.content:
                content.append({"type": "text", "text": m.content})
            for tu in m.tool_uses:
                content.append({
                    "type": "tool_use",
                    "id": tu.tool_use_id,
                    "name": tu.tool_name,
                    "input": tu.arguments,
                })
            if not content:
                content.append({"type": "text", "text": ""})
            result.append({"role": "assistant", "content": content})
        elif m.tool_results:
            content = []
            for tr in m.tool_results:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                })
            result.append({"role": "user", "content": content})
        else:
            # 合并连续的 user 纯文本消息（system-reminder 或普通 user 文本）。
            # 不合并到 tool_result 类型的 user 消息中（content 是 list）。
            if (
                m.role == "user"
                and result
                and result[-1]["role"] == "user"
                and isinstance(result[-1]["content"], str)
            ):
                result[-1]["content"] = result[-1]["content"] + "\n" + m.content
            else:
                result.append({"role": m.role, "content": m.content})
    return result


def build_openai_input(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses:
            # Responses API: thinking blocks 作为 reasoning item 回传。
            for tb in (m.thinking_blocks or []):
                result.append({
                    "type": "reasoning",
                    "id": tb.signature,
                    "summary": [{"type": "summary_text", "text": tb.thinking}],
                })
            if m.content:
                result.append({"role": "assistant", "content": m.content})
            for tu in m.tool_uses:
                result.append({
                    "type": "function_call",
                    "name": tu.tool_name,
                    "call_id": tu.tool_use_id,
                    "arguments": json.dumps(tu.arguments),
                })
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "type": "function_call_output",
                    "call_id": tr.tool_use_id,
                    "output": tr.content,
                })
        else:
            # 非 tool 的 assistant 消息也回传 reasoning。
            for tb in (m.thinking_blocks or []):
                result.append({
                    "type": "reasoning",
                    "id": tb.signature,
                    "summary": [{"type": "summary_text", "text": tb.thinking}],
                })
            result.append({"role": m.role, "content": m.content})
    return result


def build_chat_completion_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """OpenAI Chat Completions 格式。

    - 用户消息：{"role": "user", "content": "..."}
    - 助手文本+工具调用：{"role": "assistant", "content": "...", "tool_calls": [...]}
    - 工具结果：{"role": "tool", "tool_call_id": "...", "content": "..."}
    - thinking 块作为 reasoning_content 回传（DeepSeek/小米等 provider 要求）。
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        reasoning = "".join(tb.thinking for tb in m.thinking_blocks) if m.thinking_blocks else ""

        if m.tool_uses:
            tool_calls = []
            for tu in m.tool_uses:
                tool_calls.append({
                    "id": tu.tool_use_id,
                    "type": "function",
                    "function": {
                        "name": tu.tool_name,
                        "arguments": json.dumps(tu.arguments),
                    },
                })
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": m.content or None,
                "tool_calls": tool_calls,
            }
            if reasoning:
                msg["reasoning_content"] = reasoning
            result.append(msg)
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tr.content,
                })
        else:
            msg = {"role": m.role, "content": m.content}
            if reasoning:
                msg["reasoning_content"] = reasoning
            result.append(msg)
    return result


def build_messages(messages: list[Message], protocol: str = "anthropic") -> list[dict[str, Any]]:
    if protocol == "openai":
        return build_openai_input(messages)
    if protocol == "openai-compat":
        return build_chat_completion_messages(messages)
    return build_anthropic_messages(messages)
