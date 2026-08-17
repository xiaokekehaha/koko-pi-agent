# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from enum import StrEnum


class LifecycleEvent(StrEnum):
    # 会话（Session）级别
    SESSION_START = "session_start"
    SESSION_END = "session_end"


    # 轮次（Turn）级别
    TURN_START = "turn_start"
    TURN_END = "turn_end"


    # 工具（Tool）级别
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"

    # 消息（Message）级别
    PRE_SEND = "pre_send"
    POST_RECEIVE = "post_receive"

    # 系统（System）级别
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    COMPACT = "compact"
    PERMISSION_REQUEST = "permission_request"
    FILE_CHANGE = "file_change"
    COMMAND_EXECUTE = "command_execute"

