# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from dataclasses import replace

from koko_pi_agent.conversation import Message, ToolResultBlock

# Anthropic 要求每个 tool_use 都有配对的 tool_result，缺一个整条请求就会被拒。
# 会话历史出现不配对的情况有几种来路：用户中断在工具执行途中、进程退出后从磁盘
# 恢复会话、并发写入交错。这里在发请求前统一补齐，各前端不必各写一遍。

# 用于补上没有结果的工具调用。工具可能压根没启动，也可能跑到一半被打断，
# 所以措辞上不能断言它没有产生任何副作用。
INTERRUPTED_TOOL_RESULT = (
    "Tool execution was interrupted. The tool may or may not have completed; "
    "verify before relying on its effects."
)

# 用于用户明确拒绝授权的工具调用。这种情况可以断言什么都没改，必须讲清楚，
# 否则模型会以为修改已经生效并继续往下走。
REJECTED_TOOL_RESULT = (
    "The user rejected this tool use. Nothing was changed "
    "(for file edits, the new content was NOT written)."
)


def ensure_tool_pairing(messages: list[Message]) -> list[Message]:
    """返回一份修好配对关系的消息副本，输入不会被修改。

    做两件事：给没有结果的 tool_use 补一条标记为错误的 tool_result（紧跟其后），
    丢掉找不到对应 tool_use 的孤儿 tool_result。补出来的内容不写回对话历史：
    历史应当如实记录发生过什么，补位只是为了让这一次请求合法。
    """
    resolved: set[str] = set()
    issued: set[str] = set()
    for m in messages:
        for tr in m.tool_results or []:
            resolved.add(tr.tool_use_id)
        for tu in m.tool_uses or []:
            issued.add(tu.tool_use_id)

    out: list[Message] = []
    for m in messages:
        current = m
        if m.tool_results:
            kept = [tr for tr in m.tool_results if tr.tool_use_id in issued]
            if not kept and not m.content and not m.tool_uses:
                continue  # 整条消息只剩空壳，丢掉以免破坏角色交替
            current = replace(m, tool_results=kept)
        out.append(current)

        missing = []
        for tu in m.tool_uses or []:
            if tu.tool_use_id in resolved:
                continue
            missing.append(
                ToolResultBlock(
                    tool_use_id=tu.tool_use_id,
                    content=INTERRUPTED_TOOL_RESULT,
                    is_error=True,
                )
            )
            resolved.add(tu.tool_use_id)
        if missing:
            out.append(Message(role="user", content="", tool_results=missing))
    return out
