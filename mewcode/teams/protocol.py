# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""队友之间的结构化消息协议。

除了纯文本，队友之间还走几种结构化消息。它们都带一个 request_id，应答回来时
原样带回，Lead 才能把应答和自己发出的那条请求对上号：同时向三个队友发关闭请求时，
三条应答不靠 ID 是分不清谁是谁的。
"""

from __future__ import annotations

import secrets

from mewcode.teams.mailbox import MailboxMessage, create_message

# 普通文本消息，直接拼进队友下一轮的 prompt
TEXT = "text"
# 由 Lead 发起，请队友收工。队友可以拒绝
SHUTDOWN_REQUEST = "shutdown_request"
# 队友对关闭请求的答复，approve 为 False 表示还没干完
SHUTDOWN_RESPONSE = "shutdown_response"
# 由队友发起，把计划交给 Lead 审批
PLAN_APPROVAL_REQUEST = "plan_approval_request"
# Lead 的审批结果，驳回时 content 里带修改意见
PLAN_APPROVAL_RESPONSE = "plan_approval_response"

VALID_MESSAGE_TYPES = frozenset({
    TEXT,
    SHUTDOWN_REQUEST,
    SHUTDOWN_RESPONSE,
    PLAN_APPROVAL_REQUEST,
    PLAN_APPROVAL_RESPONSE,
})

# 关闭消息的文本前缀，窗格队友可能是旧版本进程拉起来的，仍按这个前缀识别
SHUTDOWN_PREFIX = "[shutdown]"


def new_request_id() -> str:
    """生成请求标识。

    用随机串而不是自增序号，因为请求可能由不同进程里的队友发起，自增序号跨进程会撞。
    """
    return f"req-{secrets.token_hex(8)}"


def shutdown_request(from_agent: str, to_agent: str, reason: str = "") -> MailboxMessage:
    """关闭请求。正文里放原因，队友要拿它判断该不该同意。"""
    why = reason or "team is wrapping up"
    return create_message(
        from_agent, f"{SHUTDOWN_PREFIX} {why}",
        message_type=SHUTDOWN_REQUEST,
        request_id=new_request_id(),
    )


def shutdown_response(
    from_agent: str, to_agent: str, request_id: str, approve: bool, reason: str = ""
) -> MailboxMessage:
    """队友对关闭请求的答复。"""
    return create_message(
        from_agent, reason,
        message_type=SHUTDOWN_RESPONSE,
        request_id=request_id,
        approve=approve,
    )


def plan_approval_request(from_agent: str, to_agent: str, plan: str) -> MailboxMessage:
    """计划审批请求，正文是计划全文。"""
    return create_message(
        from_agent, plan,
        message_type=PLAN_APPROVAL_REQUEST,
        request_id=new_request_id(),
    )


def plan_approval_response(
    from_agent: str, to_agent: str, request_id: str, approve: bool, feedback: str = ""
) -> MailboxMessage:
    """审批结果，驳回时 feedback 说明哪里要改。"""
    return create_message(
        from_agent, feedback,
        message_type=PLAN_APPROVAL_RESPONSE,
        request_id=request_id,
        approve=approve,
    )


def request_id_of(msg: MailboxMessage) -> str:
    """取出消息携带的请求标识，没有则返回空串。"""
    return msg.request_id


def is_shutdown_request(msg: MailboxMessage) -> bool:
    """判断消息是不是关闭请求。

    除了看 type，还认 "[shutdown]" 文本前缀：窗格队友是独立进程，可能是
    旧版本启动的；而且用户手动往信箱里塞一行也该管用。
    """
    if msg.type == SHUTDOWN_REQUEST:
        return True
    return msg.text.strip().startswith(SHUTDOWN_PREFIX)


def approved(msg: MailboxMessage) -> bool:
    """应答是否为同意。

    字段缺省时按不同意处理，宁可让 Lead 多等一轮，也不能把没表态当成点头。
    """
    return msg.approve is True
