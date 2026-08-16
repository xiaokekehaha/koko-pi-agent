from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Literal

from mewcode.conversation import ConversationManager, ToolUseBlock
from mewcode.conversation import ThinkingBlock as ConvThinkingBlock
from mewcode.prompts import build_environment_context
from mewcode.runtime.events import (
    AgentEvent,
    ErrorEvent,
    EventSink,
    LoopComplete,
    MessageFinished,
    MessageStarted,
    RetryEvent,
    RunFailed,
    RunFinished,
    RunInputDelivered,
    RunResult,
    RunStarted,
    StreamText,
    ThinkingText,
    ToolUseEvent,
    TurnComplete,
    TurnStarted,
    UsageEvent,
)
from mewcode.runtime.run_control import (
    HardStopReason,
    QueuedRunInput,
    RunControl,
    RunControlState,
    RunInputClosedError,
    RunInputKind,
    RunInputReceipt,
    TurnDirective,
    TurnReason,
)
from mewcode.runtime.tool_pipeline import (
    ApprovalAdapter,
    CompletedAssistantMessage,
    ToolBatchRequest,
    ToolPipeline,
)
from mewcode.runtime.turn_preparer import TurnPreparer
from mewcode.tools.base import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)

log = logging.getLogger(__name__)

MAX_TOKENS_CEILING = 64_000
MAX_OUTPUT_TOKENS_RECOVERIES = 3
MEMORY_EXTRACTION_INTERVAL = 1


@dataclass
class ThinkingBlock:
    thinking: str
    signature: str


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCallComplete] = field(default_factory=list)
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0


class StreamCollector:
    def __init__(self) -> None:
        self.response = LLMResponse()

    async def consume(
        self, stream: AsyncIterator[StreamEvent]
    ) -> AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text
                yield StreamText(text=event.text)
            elif isinstance(event, ThinkingDelta):
                yield ThinkingText(text=event.text)
            elif isinstance(event, ThinkingComplete):
                self.response.thinking_blocks.append(
                    ThinkingBlock(
                        thinking=event.thinking,
                        signature=event.signature,
                    )
                )
            elif isinstance(event, (ToolCallStart, ToolCallDelta)):
                continue
            elif isinstance(event, ToolCallComplete):
                self.response.tool_calls.append(event)
                yield ToolUseEvent(
                    tool_name=event.tool_name,
                    tool_id=event.tool_id,
                    arguments=event.arguments,
                )
            elif isinstance(event, StreamEnd):
                self.response.stop_reason = event.stop_reason
                self.response.input_tokens = event.input_tokens
                self.response.output_tokens = event.output_tokens
                self.response.cache_read = event.cache_read
                self.response.cache_creation = event.cache_creation


class RunStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SETTLING = "settling"
    IDLE = "idle"


class RunCancellation:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


@dataclass(frozen=True)
class RunRequest:
    conversation: ConversationManager


def _result_reason(result: RunResult) -> TurnReason:
    if result.status == "cancelled":
        return "cancelled"
    if result.status == "failed":
        return "failed"
    if result.status == "max_turns":
        return "max_turns"
    return "natural"


class AgentRun:
    def __init__(
        self,
        loop: AgentLoop,
        request: RunRequest,
        emit: EventSink,
        on_idle: Callable[[AgentRun], None],
    ) -> None:
        self.run_id = uuid.uuid4().hex
        self._loop = loop
        self._request = request
        self._emit = emit
        self._on_idle = on_idle
        self._cancellation = RunCancellation()
        self._control = RunControl()
        self._status = RunStatus.CREATED
        self._result: RunResult | None = None
        self._idle = asyncio.Event()
        self._task: asyncio.Task[RunResult] | None = None

    @property
    def status(self) -> RunStatus:
        return self._status

    @property
    def result(self) -> RunResult | None:
        return self._result

    def steer(self, text: str) -> RunInputReceipt:
        return self._enqueue_input(RunInputKind.STEERING, text)

    def follow_up(self, text: str) -> RunInputReceipt:
        return self._enqueue_input(RunInputKind.FOLLOW_UP, text)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("AgentRun has already started")
        self._task = asyncio.create_task(self._drive())
        self._task.add_done_callback(self._handle_task_done)

    def cancel(self) -> None:
        if self._status in (
            RunStatus.CANCELLING,
            RunStatus.SETTLING,
            RunStatus.IDLE,
        ):
            return
        self._control.seal("cancelled")
        self._cancellation.cancel()
        self._status = RunStatus.CANCELLING
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait_until_idle(self) -> RunResult:
        if self._task is None:
            raise RuntimeError("AgentRun has not started")
        await self._idle.wait()
        if self._task is not asyncio.current_task() and not self._task.cancelled():
            await asyncio.shield(self._task)
        assert self._result is not None
        return self._result

    async def _drive(self) -> RunResult:
        self._status = RunStatus.RUNNING
        try:
            self._result = await self._loop.run(
                self._request,
                self._emit,
                self._cancellation,
                self.run_id,
                self._control,
            )
        except asyncio.CancelledError:
            self._result = RunResult(status="cancelled", turns=0, final_text="")
        except Exception as exc:  # noqa: BLE001 - run boundary normalizes failures
            self._result = RunResult(
                status="failed", turns=0, final_text="", error=str(exc)
            )
        finally:
            assert self._result is not None
            self._settle(self._result)
        assert self._result is not None
        return self._result

    def _handle_task_done(self, task: asyncio.Task[RunResult]) -> None:
        if self._idle.is_set():
            return
        if task.cancelled():
            result = RunResult(status="cancelled", turns=0, final_text="")
        else:
            try:
                result = task.result()
            except Exception as exc:  # noqa: BLE001 - task boundary fallback
                result = RunResult(
                    status="failed", turns=0, final_text="", error=str(exc)
                )
        self._settle(result)

    def _settle(self, result: RunResult) -> None:
        if self._idle.is_set():
            return
        if self._control.state is RunControlState.OPEN:
            self._control.seal(_result_reason(result))
        undelivered = self._control.recover_undelivered()
        if undelivered:
            result = replace(
                result,
                undelivered_inputs=(*result.undelivered_inputs, *undelivered),
            )
        self._result = result
        self._status = RunStatus.SETTLING
        self._on_idle(self)
        self._status = RunStatus.IDLE
        self._idle.set()

    def _enqueue_input(
        self,
        kind: RunInputKind,
        text: str,
    ) -> RunInputReceipt:
        if self._status not in (RunStatus.CREATED, RunStatus.RUNNING):
            raise RunInputClosedError(
                f"AgentRun is {self._status.value} and no longer accepts queued input"
            )
        return self._control.enqueue(kind, text)


class AgentLoop:
    """The single model -> tool -> model loop used by every adapter."""

    def __init__(self, agent: Any, approval: ApprovalAdapter) -> None:
        self._agent = agent
        self._pipeline = ToolPipeline(
            agent.registry,
            permission_checker=agent.permission_checker,
            approval=approval,
            hook_engine=agent.hook_engine,
            recovery_state=agent.recovery_state,
        )

    async def run(
        self,
        request: RunRequest,
        emit: EventSink,
        cancellation: RunCancellation,
        run_id: str,
        control: RunControl,
    ) -> RunResult:
        await emit(RunStarted(run_id=run_id))
        self._session_started = False
        failure_messages: list[str] = []
        try:
            result = await self._run_loop(request, emit, cancellation, control)
        except asyncio.CancelledError:
            control.seal("cancelled")
            result = RunResult(
                status="cancelled",
                turns=getattr(self, "_turn", 0),
                final_text=getattr(self, "_last_text", ""),
            )
        except Exception as exc:
            log.exception("Agent run failed")
            control.seal("failed")
            failure_messages.append(str(exc))
            result = RunResult(
                status="failed",
                turns=getattr(self, "_turn", 0),
                final_text=getattr(self, "_last_text", ""),
                error=str(exc),
            )

        if self._session_started:
            try:
                await self._agent._run_hook("session_end", emit)
            except asyncio.CancelledError:
                control.seal("cancelled")
                result = replace(result, status="cancelled")
            except Exception as exc:
                log.exception("Agent session_end hook failed")
                failure_messages.append(str(exc))
                control.seal("failed")
                if result.status != "cancelled":
                    result = replace(
                        result,
                        status="failed",
                        error="; ".join(failure_messages),
                    )

        if failure_messages:
            message = "; ".join(failure_messages)
            try:
                await emit(RunFailed(run_id=run_id, message=message))
                await emit(ErrorEvent(message=message))
            except Exception:
                log.debug("Unable to emit run failure events", exc_info=True)

        result = self._finalize_result(result, control)
        await emit(RunFinished(run_id=run_id, result=result))
        return result

    async def _run_loop(
        self,
        request: RunRequest,
        emit: EventSink,
        cancellation: RunCancellation,
        control: RunControl,
    ) -> RunResult:
        agent = self._agent
        conversation = request.conversation
        agent._current_conversation = conversation
        agent._conversation = conversation
        env_context = build_environment_context(
            agent.work_dir,
            agent.active_skills,
            agent._skill_catalog,
            agent._agent_catalog,
        )
        conversation.inject_environment(env_context)
        memory_content = agent.memory_manager.load() if agent.memory_manager else ""
        conversation.inject_long_term_memory(agent.instructions_content, memory_content)
        turn_preparer = TurnPreparer(agent, env_context)

        await agent._run_hook("session_start", emit)
        self._session_started = True

        self._turn = 0
        self._last_text = ""
        max_tokens_escalated = False
        output_recoveries = 0

        await self._deliver_inputs(
            conversation,
            control.before_first_turn(),
            emit,
        )

        while True:
            cancellation.raise_if_cancelled()
            self._turn += 1
            iteration = self._turn

            await emit(TurnStarted(turn=iteration))
            await agent._run_hook("turn_start", emit)
            prepared_call = await turn_preparer.prepare(
                conversation,
                iteration,
                emit,
                cancellation,
            )
            collector = StreamCollector()
            await emit(MessageStarted(turn=iteration))
            stream = agent.client.stream(
                conversation,
                system=prepared_call.system_prompt,
                tools=list(prepared_call.tool_schemas),
            )
            async for event in collector.consume(stream):
                cancellation.raise_if_cancelled()
                await emit(event)
            response = collector.response
            await emit(
                MessageFinished(
                    turn=iteration,
                    text=response.text,
                    stop_reason=response.stop_reason,
                )
            )
            if response.text:
                self._last_text = response.text

            await agent._run_hook("post_receive", emit, message=response.text)
            agent.total_input_tokens += response.input_tokens
            agent.total_output_tokens += response.output_tokens
            await emit(
                UsageEvent(
                    input_tokens=agent.total_input_tokens,
                    output_tokens=agent.total_output_tokens,
                )
            )

            conv_thinking = [
                ConvThinkingBlock(thinking=block.thinking, signature=block.signature)
                for block in response.thinking_blocks
            ]
            completed = CompletedAssistantMessage(
                text=response.text,
                tool_calls=tuple(response.tool_calls),
                stop_reason=response.stop_reason,
            )

            if completed.is_truncated:
                await self._record_truncated_response(
                    conversation, response, conv_thinking, completed, emit, cancellation
                )
                retry_message: str | None = None
                retry_event: RetryEvent | None = None
                if not max_tokens_escalated:
                    agent.client.set_max_output_tokens(MAX_TOKENS_CEILING)
                    max_tokens_escalated = True
                    retry_message = (
                        "Output token limit hit. Resume directly from where you stopped. "
                        "Do not apologize or repeat previous content. Pick up mid-thought if needed."
                    )
                    retry_event = RetryEvent(reason="max_tokens escalation")
                elif output_recoveries < MAX_OUTPUT_TOKENS_RECOVERIES:
                    output_recoveries += 1
                    retry_message = (
                        "Output token limit hit. Resume directly from where you stopped. "
                        "Break remaining work into smaller pieces."
                    )
                    retry_event = RetryEvent(
                        reason=(
                            "max_tokens recovery "
                            f"{output_recoveries}/{MAX_OUTPUT_TOKENS_RECOVERIES}"
                        )
                    )

                await agent._run_hook("turn_end", emit)
                if retry_message is not None and retry_event is not None:
                    directive = control.after_turn(
                        would_stop=False,
                        continuation_allowed=self._continuation_allowed(iteration),
                        continue_reason="retry",
                    )
                    await emit(
                        TurnComplete(
                            turn=iteration,
                            will_continue=directive.continue_run,
                            reason=directive.reason,
                        )
                    )
                    if not directive.continue_run:
                        return await self._max_turn_result(iteration, emit)
                    conversation.add_user_message(retry_message)
                    await emit(retry_event)
                    await self._deliver_inputs(
                        conversation,
                        directive.deliveries,
                        emit,
                    )
                    continue

                message = "Output token limit recovery exhausted"
                control.after_turn(would_stop=False, hard_stop="failed")
                await emit(
                    TurnComplete(
                        turn=iteration,
                        will_continue=False,
                        reason="failed",
                    )
                )
                await emit(ErrorEvent(message=message))
                await emit(LoopComplete(total_turns=iteration))
                return RunResult(
                    status="failed",
                    turns=iteration,
                    final_text=self._last_text,
                    error=message,
                )

            output_recoveries = 0
            if not response.tool_calls:
                conversation.add_assistant_message(
                    response.text, thinking_blocks=conv_thinking
                )
                self._record_usage_anchor(conversation, response)
                await self._finish_natural_turn(conversation, response.text, emit)
                directive = await self._finish_turn(
                    control,
                    conversation,
                    emit,
                    iteration,
                    would_stop=True,
                )
                if directive.continue_run:
                    continue
                if directive.reason == "max_turns":
                    return await self._max_turn_result(iteration, emit)
                await emit(LoopComplete(total_turns=iteration))
                return RunResult(
                    status="completed",
                    turns=iteration,
                    final_text=self._last_text,
                )

            tool_uses = [
                ToolUseBlock(
                    tool_use_id=call.tool_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                )
                for call in response.tool_calls
            ]
            conversation.add_assistant_message(
                response.text,
                tool_uses,
                thinking_blocks=conv_thinking,
            )
            self._record_usage_anchor(conversation, response)
            batch_request = ToolBatchRequest(
                assistant_message=completed,
                session_dir=agent.session_dir,
            )
            try:
                batch = await self._pipeline.execute_batch(
                    batch_request, emit, cancellation
                )
            except asyncio.CancelledError:

                async def discard(_event: AgentEvent) -> None:
                    return None

                batch = await self._pipeline.cancelled_batch(batch_request, discard)
                conversation.add_tool_results_message(list(batch.messages))
                raise
            conversation.add_tool_results_message(list(batch.messages))

            if (
                agent.memory_recall_task
                and not agent._memory_recall_consumed
                and agent.memory_recall_task.done()
            ):
                try:
                    recall = agent.memory_recall_task.result()
                    if recall:
                        conversation.add_system_reminder(recall)
                except Exception:
                    log.debug("Memory recall task failed", exc_info=True)
                agent._memory_recall_consumed = True

            await agent._run_hook("turn_end", emit)
            directive = await self._finish_turn(
                control,
                conversation,
                emit,
                iteration,
                would_stop=False,
                hard_stop="terminate" if batch.terminate else None,
            )
            if directive.continue_run:
                continue
            if directive.reason == "max_turns":
                return await self._max_turn_result(iteration, emit)
            await emit(LoopComplete(total_turns=iteration))
            return RunResult(
                status="completed",
                turns=iteration,
                final_text=self._last_text,
            )

    async def _finish_turn(
        self,
        control: RunControl,
        conversation: ConversationManager,
        emit: EventSink,
        iteration: int,
        *,
        would_stop: bool,
        hard_stop: HardStopReason | None = None,
        continue_reason: Literal["tool_calls", "retry"] = "tool_calls",
    ) -> TurnDirective:
        directive = control.after_turn(
            would_stop=would_stop,
            hard_stop=hard_stop,
            continuation_allowed=self._continuation_allowed(iteration),
            continue_reason=continue_reason,
        )
        await emit(
            TurnComplete(
                turn=iteration,
                will_continue=directive.continue_run,
                reason=directive.reason,
            )
        )
        await self._deliver_inputs(conversation, directive.deliveries, emit)
        return directive

    def _continuation_allowed(self, iteration: int) -> bool:
        max_iterations = self._agent.max_iterations
        return max_iterations <= 0 or iteration < max_iterations

    async def _max_turn_result(
        self,
        iteration: int,
        emit: EventSink,
    ) -> RunResult:
        max_iterations = self._agent.max_iterations
        message = f"Agent reached maximum iterations ({max_iterations})"
        await emit(ErrorEvent(message=message))
        await emit(LoopComplete(total_turns=iteration))
        return RunResult(
            status="max_turns",
            turns=iteration,
            final_text=self._last_text,
            error=message,
        )

    @staticmethod
    async def _deliver_inputs(
        conversation: ConversationManager,
        deliveries: tuple[QueuedRunInput, ...],
        emit: EventSink,
    ) -> None:
        if not deliveries:
            return
        kind = deliveries[0].kind
        if any(item.kind is not kind for item in deliveries):
            raise RuntimeError("A delivery batch must contain one run input kind")
        for item in deliveries:
            conversation.add_user_message(item.text)
        await emit(
            RunInputDelivered(
                kind=kind,
                input_ids=tuple(item.input_id for item in deliveries),
            )
        )

    @staticmethod
    def _finalize_result(result: RunResult, control: RunControl) -> RunResult:
        if control.state is RunControlState.OPEN:
            control.seal(_result_reason(result))
        undelivered = control.recover_undelivered()
        if not undelivered:
            return result
        return replace(
            result,
            undelivered_inputs=(*result.undelivered_inputs, *undelivered),
        )

    async def _record_truncated_response(
        self,
        conversation: ConversationManager,
        response: LLMResponse,
        thinking_blocks: list[ConvThinkingBlock],
        completed: CompletedAssistantMessage,
        emit: EventSink,
        cancellation: RunCancellation,
    ) -> None:
        if response.tool_calls:
            conversation.add_assistant_message(
                response.text,
                [
                    ToolUseBlock(
                        tool_use_id=call.tool_id,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                    )
                    for call in response.tool_calls
                ],
                thinking_blocks=thinking_blocks,
            )
            batch = await self._pipeline.execute_batch(
                ToolBatchRequest(
                    assistant_message=completed,
                    session_dir=self._agent.session_dir,
                ),
                emit,
                cancellation,
            )
            conversation.add_tool_results_message(list(batch.messages))
        elif response.text or thinking_blocks:
            conversation.add_assistant_message(
                response.text, thinking_blocks=thinking_blocks
            )
        self._record_usage_anchor(conversation, response)

    async def _finish_natural_turn(
        self,
        conversation: ConversationManager,
        text: str,
        emit: EventSink,
    ) -> None:
        agent = self._agent
        agent._loop_count += 1
        if agent._loop_count % MEMORY_EXTRACTION_INTERVAL == 0 and agent.memory_manager:
            asyncio.create_task(agent._extract_memories(conversation))
        if agent._consolidator is not None:
            asyncio.create_task(
                agent._consolidator.maybe_run(
                    agent.client, conversation, agent.protocol
                )
            )
        await agent._run_hook("turn_end", emit)
        if agent.file_history is not None:
            summary = text[:60] + "..." if len(text) > 60 else text
            agent.file_history.make_snapshot(len(conversation.history), summary)

    @staticmethod
    def _record_usage_anchor(
        conversation: ConversationManager, response: LLMResponse
    ) -> None:
        conversation.record_usage_anchor(
            response.input_tokens,
            response.output_tokens,
            response.cache_read,
            response.cache_creation,
        )


@dataclass
class _EventEnvelope:
    event: AgentEvent
    acknowledged: asyncio.Future[None]


class StreamingEventAdapter:
    """Turns the async EventSink contract into the legacy async iterator API."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[_EventEnvelope] = asyncio.Queue()

    async def emit(self, event: AgentEvent) -> None:
        acknowledged = asyncio.get_running_loop().create_future()
        await self._queue.put(_EventEnvelope(event, acknowledged))
        await acknowledged

    async def events(self, run: AgentRun) -> AsyncIterator[AgentEvent]:
        current: _EventEnvelope | None = None
        try:
            while True:
                current = await self._queue.get()
                yield current.event
                if not current.acknowledged.done():
                    current.acknowledged.set_result(None)
                if isinstance(current.event, RunFinished):
                    break
                current = None
            await run.wait_until_idle()
        finally:
            if current is not None and not current.acknowledged.done():
                current.acknowledged.set_result(None)
            if run.status != RunStatus.IDLE:
                run.cancel()
                while run.status != RunStatus.IDLE:
                    try:
                        envelope = await asyncio.wait_for(
                            self._queue.get(), timeout=0.05
                        )
                    except TimeoutError:
                        continue
                    if not envelope.acknowledged.done():
                        envelope.acknowledged.set_result(None)
                await run.wait_until_idle()
