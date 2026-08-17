# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from koko_pi_agent.teams import protocol
from koko_pi_agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from koko_pi_agent.teams.manager import TeamManager

log = logging.getLogger(__name__)


class SendMessageParams(BaseModel):
    to: str
    content: str
    type: str = "text"
    # 结构化消息用：request_id 让应答对上请求，approve 是表态
    request_id: str = ""
    approve: bool | None = None


VALID_MESSAGE_TYPES = protocol.VALID_MESSAGE_TYPES


class SendMessageTool(Tool):
    name = "SendMessage"
    description = (
        "Send a message to a teammate by name or agent ID. "
        "Use to='*' to broadcast to all teammates. "
        "Set type='shutdown_request' to ask a teammate to wrap up; it replies with "
        "shutdown_response. Set type='plan_approval_response' together with request_id "
        "and approve to answer a teammate's plan; when rejecting, put your feedback in content."
    )
    params_model = SendMessageParams
    category = "command"
    is_concurrency_safe = True


    def __init__(
        self,
        team_manager: TeamManager,
        team_name: str,
        from_agent_id: str,
        from_agent_name: str = "",
    ) -> None:
        self._team_manager = team_manager
        self._team_name = team_name
        self._from_agent_id = from_agent_id
        self._from_agent_name = from_agent_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: SendMessageParams = params  # type: ignore[assignment]

        if p.type not in VALID_MESSAGE_TYPES:
            return ToolResult(
                output=f"Invalid type '{p.type}'. Must be one of: {', '.join(sorted(VALID_MESSAGE_TYPES))}",
                is_error=True,
            )

        from koko_pi_agent.teams.mailbox import create_message
        from koko_pi_agent.teams.registry import AgentNameRegistry

        team = self._team_manager.get_team(self._team_name)
        if team is None:
            return ToolResult(output=f"Team '{self._team_name}' not found", is_error=True)

        mailbox = self._team_manager.get_mailbox(self._team_name)
        if mailbox is None:
            return ToolResult(output=f"Mailbox not found for team '{self._team_name}'", is_error=True)

        sender = self._from_agent_name or self._from_agent_id

        # 结构化消息要带 request_id 和表态，拼进正文的话收件方还得从自然语言里猜，
        # 那就退回到「靠理解措辞来协调」了。
        request_id = ""
        if p.type != protocol.TEXT:
            if p.type == protocol.PLAN_APPROVAL_RESPONSE and (
                not p.request_id or p.approve is None
            ):
                return ToolResult(
                    output="plan_approval_response requires both 'request_id' and 'approve'.",
                    is_error=True,
                )
            if p.type == protocol.SHUTDOWN_RESPONSE and p.approve is None:
                return ToolResult(
                    output="shutdown_response requires 'approve'.", is_error=True
                )
            request_id = p.request_id or protocol.new_request_id()

        content = p.content
        if p.type == protocol.SHUTDOWN_REQUEST:
            # 带上文本前缀，旧版本拉起的窗格队友也能认出来
            content = f"{protocol.SHUTDOWN_PREFIX} {p.content}"

        msg = create_message(
            from_agent=sender,
            text=content,
            message_type=p.type,
            request_id=request_id,
            approve=p.approve,
        )

        registry = AgentNameRegistry.instance()

        if p.to == "*":
            member_ids = [
                m.agent_id for m in team.members
                if m.agent_id != self._from_agent_id
            ]
            if team.lead_agent_id != self._from_agent_id:
                member_ids.append(team.lead_agent_id)
            mailbox.broadcast(member_ids, msg, exclude=self._from_agent_id)
            self._wake_pane_members(team, member_ids)
            return ToolResult(output=f"Message broadcast to {len(member_ids)} teammates.")

        target_id = registry.resolve(p.to)
        if target_id is None:
            return ToolResult(
                output=f"Cannot resolve recipient '{p.to}'. Check the name or agent ID.",
                is_error=True,
            )

        mailbox.write(target_id, msg)
        self._wake_pane(target_id)

        return ToolResult(output=f"Message sent to '{p.to}'.")


    def _wake_pane(self, agent_id: str) -> None:
        pane_id = self._team_manager.get_pane_id(agent_id)
        if pane_id is None:
            return
        try:
            from koko_pi_agent.teams.spawn_tmux import send_keys_to_pane
            send_keys_to_pane(pane_id, "")
        except Exception:
            pass

    def _wake_pane_members(self, team: Any, agent_ids: list[str]) -> None:
        for aid in agent_ids:
            self._wake_pane(aid)
