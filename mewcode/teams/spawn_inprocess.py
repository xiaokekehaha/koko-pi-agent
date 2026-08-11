# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mewcode.teams import protocol
from mewcode.teams.mailbox import Mailbox, MailboxMessage, create_message
from mewcode.teams.progress import TeammateProgress, random_verb

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.conversation import ConversationManager
    from mewcode.teams.models import TeammateInfo

log = logging.getLogger(__name__)

# Idle 轮询间隔（秒）
IDLE_POLL_INTERVAL = 0.5

# shutdown 消息前缀
SHUTDOWN_PREFIX = "[shutdown]"

# lead 名称
LEAD_NAME = "lead"


def _is_shutdown_request(msg: MailboxMessage) -> bool:
    """判断邮箱消息是否为关闭请求，结构化类型和文本前缀都认。"""
    return protocol.is_shutdown_request(msg)


def _create_idle_notification(member_name: str, reason: str) -> MailboxMessage:
    """构造 idle 通知消息，发给 lead 表明 teammate 当前轮次已完成。"""
    return create_message(
        from_agent=member_name,
        text=f"[idle] {member_name} (reason: {reason})",
    )


def _inject_pending_messages(mailbox: Mailbox, member_name: str) -> str:
    """读取 teammate 邮箱中的未读消息，拼成 system-reminder 字符串。"""
    msgs = mailbox.consume(member_name)
    if not msgs:
        return ""
    parts = ["You have new messages:\n"]
    for m in msgs:
        parts.append(f"From {m.from_agent}: {m.text}\n")
    return "\n".join(parts)


async def _wait_for_next_prompt_or_shutdown(
    mailbox: Mailbox,
    member_name: str,
) -> tuple[str, MailboxMessage | None]:
    """阻塞轮询邮箱，等到有新消息后返回 (prompt, shutdown_msg)。

    收到关闭请求时返回那条消息本身而不是布尔值，调用方要拿它的 request_id 做应答。
    普通消息则拼成下一轮的 prompt。
    """
    while True:
        await asyncio.sleep(IDLE_POLL_INTERVAL)

        msgs = mailbox.consume(member_name)
        if not msgs:
            continue

        shutdown: MailboxMessage | None = None
        keep: list[MailboxMessage] = []
        for m in msgs:
            if _is_shutdown_request(m):
                shutdown = m
            else:
                keep.append(m)

        if shutdown is not None:
            return "", shutdown

        # 把剩余消息拼成下一轮的 user prompt
        if not keep:
            continue
        parts = ["You have new messages from your team:\n"]
        for m in keep:
            parts.append(f"From {m.from_agent}: {m.text}\n")
        return "\n".join(parts), None


def _plan_mode_active(agent: Any) -> bool:
    """队友是否处在计划模式。只有被 lead 标了 plan_mode_required 的队友才会进这个模式。"""
    return bool(getattr(agent, "plan_mode", False))


def _read_plan_for_review(agent: Any) -> str:
    """读出队友写好的计划全文，交给 lead 审阅。"""
    try:
        text = agent._get_plan_path().read_text(encoding="utf-8")
        return text if text.strip() else "（计划文件为空，队友可能未按要求写入计划）"
    except Exception:
        return "（计划文件为空，队友可能未按要求写入计划）"


async def _run_plan_approval(
    mailbox: Mailbox,
    lead_key: str,
    member_name: str,
    agent: Any,
    progress: TeammateProgress,
) -> str:
    """把计划发给 lead，阻塞等待批复，返回下一轮该喂给模型的 prompt。

    队友这时候手上是只读权限，等多久都不会造成破坏，所以这里不设超时：
    与其超时后自作主张开始改文件，不如一直等着，由用户从 lead 那边推进。
    """
    req = protocol.plan_approval_request(member_name, lead_key, _read_plan_for_review(agent))
    mailbox.write(lead_key, req)
    progress.status = "awaiting plan approval"
    req_id = protocol.request_id_of(req)

    while True:
        await asyncio.sleep(IDLE_POLL_INTERVAL)
        for m in mailbox.consume(member_name):
            # 只认对应这次请求的批复，别的消息留到下一轮再处理
            if (m.type == protocol.PLAN_APPROVAL_RESPONSE
                    and protocol.request_id_of(m) == req_id):
                if protocol.approved(m):
                    # 批准后切回正常权限，队友可以改文件了
                    from mewcode.permissions.modes import PermissionMode

                    agent.set_permission_mode(PermissionMode.DEFAULT)
                    return "Lead 已批准你的计划，现在按计划开始执行。"
                return (
                    f"Lead 驳回了你的计划，修改意见：{m.text}\n"
                    "请据此修订计划后再次提交。"
                )


class InProcessTeammateHandle:
    def __init__(
        self,
        agent: Agent,
        task: asyncio.Task[str],
        name: str,
        progress: TeammateProgress | None = None,
    ) -> None:
        self.agent = agent
        self.task = task
        self.name = name
        self.progress = progress


    @property
    def done(self) -> bool:
        return self.task.done()

    @property
    def result(self) -> str | None:
        if self.task.done():
            try:
                return self.task.result()
            except (asyncio.CancelledError, Exception):
                return None
        return None


    def cancel(self) -> None:
        if not self.task.done():
            self.task.cancel()


def spawn_inprocess_teammate(
    agent: Agent,
    prompt: str,
    name: str,
    conversation: ConversationManager | None = None,
    member: TeammateInfo | None = None,
    team_name: str = "",
    mailbox: Mailbox | None = None,
    lead_key: str = LEAD_NAME,
) -> InProcessTeammateHandle:

    # Create progress tracker and attach to member if provided
    progress = TeammateProgress(
        name=name,
        team_name=team_name,
        spinner_verb=random_verb(),
    )
    if member is not None:
        member.progress = progress

    def _on_event(event: dict[str, Any]) -> None:
        """Event callback wired into agent.run_to_completion."""
        event_type = event.get("type")
        if event_type == "tool_use":
            tool_name = event.get("toolName", "")
            args = event.get("args", {})
            progress.record_tool_use(tool_name, args)
        elif event_type == "usage":
            usage = event.get("usage", {})
            progress.record_tokens(
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0),
            )
        elif event_type == "stream_text":
            text = event.get("text")
            if text:
                with progress._lock:
                    progress.last_message = text

    async def _run() -> str:
        """teammate 主循环。

        有 mailbox 时进入长驻循环：执行 agent → 发 idle 通知 → 轮询等待新任务。
        没有 mailbox 时退化为单次执行（向后兼容）。
        """
        try:
            if conversation is not None:
                conv = conversation
            else:
                from mewcode.conversation import ConversationManager as CM
                conv = CM()

            next_prompt = prompt
            idle_reason = "available"

            while True:
                # 注入本轮开始前邮箱里堆积的消息
                if mailbox is not None:
                    reminder = _inject_pending_messages(mailbox, name)
                    if reminder:
                        conv.add_system_reminder(reminder)

                # 执行一个完整的 agent turn
                if next_prompt:
                    result = await agent.run_to_completion(
                        next_prompt, conv, event_callback=_on_event,
                    )
                else:
                    result = await agent.run_to_completion(
                        "", conv, event_callback=_on_event,
                    )
                next_prompt = ""

                # 没有 mailbox 时退化为单次执行（向后兼容旧调用方式）
                if mailbox is None:
                    progress.status = "completed"
                    return result

                # 更新进度状态
                if idle_reason == "failed":
                    progress.status = "failed"
                else:
                    progress.status = "idle"

                # 计划模式的队友：一轮跑完意味着它调了 ExitPlanMode，计划已经落到磁盘。
                # 把计划交给 lead 审批，通过了才解除只读限制开始动手。
                # 放在 idle 通知之前：这时候队友不是闲着等派活，而是卡在审批上，
                # 发一条 "available" 会让 lead 误以为可以塞新任务过来。
                if _plan_mode_active(agent):
                    next_prompt = await _run_plan_approval(
                        mailbox, lead_key, name, agent, progress,
                    )
                    continue

                # 通知 lead 本轮已完成。写到 lead 实际读取的邮箱键（lead_agent_id）：
                # lead 侧 drain_lead_mailbox / SendMessage 都按 lead_agent_id 存取，
                # 外部 worker 进程用同一个键才能让 idle 通知回传到 lead。
                mailbox.write(
                    lead_key,
                    _create_idle_notification(name, idle_reason),
                )
                idle_reason = "available"

                # 轮询等待 lead 下发新任务或 shutdown 指令
                new_prompt, shutdown = await _wait_for_next_prompt_or_shutdown(
                    mailbox, name,
                )
                if shutdown is not None:
                    # 收工前先给 lead 一个明确答复，让它知道可以回收窗格了。
                    # 队友这里一律同意：它已经处在空闲轮询里，手上没有干到一半的活。
                    if shutdown.type == protocol.SHUTDOWN_REQUEST:
                        mailbox.write(lead_key, protocol.shutdown_response(
                            name, lead_key, protocol.request_id_of(shutdown),
                            True, "acknowledged, shutting down",
                        ))
                    progress.status = "completed"
                    return result

                next_prompt = new_prompt

        except asyncio.CancelledError:
            progress.status = "stopped"
            raise
        except Exception:
            progress.status = "failed"
            raise

    task = asyncio.create_task(_run(), name=f"teammate-{name}")
    log.info("Spawned in-process teammate %s (verb=%s)", name, progress.spinner_verb)
    return InProcessTeammateHandle(agent=agent, task=task, name=name, progress=progress)
