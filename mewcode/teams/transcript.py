# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mewcode.conversation import ConversationManager, Message, ToolResultBlock, ToolUseBlock


def _serialize_conversation(conv: ConversationManager) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for msg in conv.history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_uses:
            entry["tool_uses"] = [
                {
                    "tool_use_id": tu.tool_use_id,
                    "tool_name": tu.tool_name,
                    "arguments": tu.arguments,
                }
                for tu in msg.tool_uses
            ]
        if msg.tool_results:
            entry["tool_results"] = [
                {
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        messages.append(entry)
    return messages


def _deserialize_conversation(data: list[dict[str, Any]]) -> ConversationManager:
    conv = ConversationManager()
    for entry in data:
        tool_uses = [
            ToolUseBlock(
                tool_use_id=tu["tool_use_id"],
                tool_name=tu["tool_name"],
                arguments=tu["arguments"],
            )
            for tu in entry.get("tool_uses", [])
        ]
        tool_results = [
            ToolResultBlock(
                tool_use_id=tr["tool_use_id"],
                content=tr["content"],
                is_error=tr.get("is_error", False),
            )
            for tr in entry.get("tool_results", [])
        ]
        msg = Message(
            role=entry["role"],
            content=entry.get("content", ""),
            tool_uses=tool_uses,
            tool_results=tool_results,
        )
        conv.history.append(msg)
    conv.env_injected = True
    conv.ltm_injected = True
    return conv


def save_transcript(
    team_name: str,
    agent_id: str,
    conversation: ConversationManager,
) -> Path:
    from mewcode.teams.models import resolve_team_dir

    transcript_dir = resolve_team_dir(team_name) / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{agent_id}.json"
    data = _serialize_conversation(conversation)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(
    team_name: str,
    agent_id: str,
) -> ConversationManager | None:
    from mewcode.teams.models import resolve_team_dir

    path = resolve_team_dir(team_name) / "transcripts" / f"{agent_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _deserialize_conversation(data)
