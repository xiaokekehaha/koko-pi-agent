from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
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
    TurnComplete,
    TurnStarted,
    UsageEvent,
)
from mewcode.runtime.agent_run import (  # noqa: F401 - compatibility re-exports
    AgentRun,
    RunCancellation,
    RunRequest,
    RunStatus,
    finalize_run_result,
)
from mewcode.runtime.model_stream import (  # noqa: F401 - compatibility re-export
    LLMResponse,
    StreamCollector,
    ThinkingBlock,
)
from mewcode.runtime.run_control import (
    HardStopReason,
    QueuedRunInput,
    RunControl,
    TurnDirective,
)
from mewcode.runtime.streaming_adapter import (  # noqa: F401 - compatibility re-export
    StreamingEventAdapter,
)
from mewcode.runtime.tool_pipeline import (
    ApprovalAdapter,
    CompletedAssistantMessage,
    ToolBatchRequest,
    ToolBatchResult,
    ToolPipeline,
)
from mewcode.runtime.turn_preparer import TurnPreparer

log = logging.getLogger(__name__)

MAX_TOKENS_CEILING = 64_000
MAX_OUTPUT_TOKENS_RECOVERIES = 3
MEMORY_EXTRACTION_INTERVAL = 1


@dataclass
class _OutputRecoveryState:
    """Tracks truncation recovery across turns within one run."""

    max_tokens_escalated: bool = False
    attempts: int = 0


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

        result = finalize_run_result(result, control)
        await emit(RunFinished(run_id=run_id, result=result))
        return result

    async def _run_loop(
        self,
        request: RunRequest,
        emit: EventSink,
        cancellation: RunCancellation,
        control: RunControl,
    ) -> RunResult:
        conversation, turn_preparer = await self._initialize_session(request, emit)
        recovery = _OutputRecoveryState()
        await self._deliver_inputs(conversation, control.before_first_turn(), emit)

        while True:
            cancellation.raise_if_cancelled()
            self._turn += 1
            iteration = self._turn
            response = await self._stream_turn(
                conversation,
                turn_preparer,
                iteration,
                emit,
                cancellation,
            )
            thinking_blocks, completed = self._response_artifacts(response)

            # A None result means RunControl selected another turn.
            if completed.is_truncated:
                result = await self._complete_truncated_response(
                    conversation,
                    response,
                    thinking_blocks,
                    completed,
                    recovery,
                    control,
                    iteration,
                    emit,
                    cancellation,
                )
            else:
                recovery.attempts = 0
                if response.tool_calls:
                    result = await self._complete_tool_response(
                        conversation,
                        response,
                        thinking_blocks,
                        completed,
                        control,
                        iteration,
                        emit,
                        cancellation,
                    )
                else:
                    result = await self._complete_natural_response(
                        conversation,
                        response,
                        thinking_blocks,
                        control,
                        iteration,
                        emit,
                    )

            if result is not None:
                return result

    async def _initialize_session(
        self,
        request: RunRequest,
        emit: EventSink,
    ) -> tuple[ConversationManager, TurnPreparer]:
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
        return conversation, turn_preparer

    async def _stream_turn(
        self,
        conversation: ConversationManager,
        turn_preparer: TurnPreparer,
        iteration: int,
        emit: EventSink,
        cancellation: RunCancellation,
    ) -> LLMResponse:
        agent = self._agent
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
        return response

    @staticmethod
    def _response_artifacts(
        response: LLMResponse,
    ) -> tuple[list[ConvThinkingBlock], CompletedAssistantMessage]:
        thinking_blocks = [
            ConvThinkingBlock(thinking=block.thinking, signature=block.signature)
            for block in response.thinking_blocks
        ]
        completed = CompletedAssistantMessage(
            text=response.text,
            tool_calls=tuple(response.tool_calls),
            stop_reason=response.stop_reason,
        )
        return thinking_blocks, completed

    async def _complete_truncated_response(
        self,
        conversation: ConversationManager,
        response: LLMResponse,
        thinking_blocks: list[ConvThinkingBlock],
        completed: CompletedAssistantMessage,
        recovery: _OutputRecoveryState,
        control: RunControl,
        iteration: int,
        emit: EventSink,
        cancellation: RunCancellation,
    ) -> RunResult | None:
        await self._record_truncated_response(
            conversation,
            response,
            thinking_blocks,
            completed,
            emit,
            cancellation,
        )
        retry = self._next_output_retry(recovery)
        await self._agent._run_hook("turn_end", emit)
        if retry is None:
            return await self._output_recovery_failed(control, iteration, emit)

        retry_message, retry_event = retry
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
        await self._deliver_inputs(conversation, directive.deliveries, emit)
        return None

    def _next_output_retry(
        self,
        recovery: _OutputRecoveryState,
    ) -> tuple[str, RetryEvent] | None:
        if not recovery.max_tokens_escalated:
            self._agent.client.set_max_output_tokens(MAX_TOKENS_CEILING)
            recovery.max_tokens_escalated = True
            return (
                "Output token limit hit. Resume directly from where you stopped. "
                "Do not apologize or repeat previous content. "
                "Pick up mid-thought if needed.",
                RetryEvent(reason="max_tokens escalation"),
            )
        if recovery.attempts >= MAX_OUTPUT_TOKENS_RECOVERIES:
            return None

        recovery.attempts += 1
        return (
            "Output token limit hit. Resume directly from where you stopped. "
            "Break remaining work into smaller pieces.",
            RetryEvent(
                reason=(
                    "max_tokens recovery "
                    f"{recovery.attempts}/{MAX_OUTPUT_TOKENS_RECOVERIES}"
                )
            ),
        )

    async def _output_recovery_failed(
        self,
        control: RunControl,
        iteration: int,
        emit: EventSink,
    ) -> RunResult:
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

    async def _complete_natural_response(
        self,
        conversation: ConversationManager,
        response: LLMResponse,
        thinking_blocks: list[ConvThinkingBlock],
        control: RunControl,
        iteration: int,
        emit: EventSink,
    ) -> RunResult | None:
        conversation.add_assistant_message(
            response.text,
            thinking_blocks=thinking_blocks,
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
        return await self._resolve_turn_directive(directive, iteration, emit)

    async def _complete_tool_response(
        self,
        conversation: ConversationManager,
        response: LLMResponse,
        thinking_blocks: list[ConvThinkingBlock],
        completed: CompletedAssistantMessage,
        control: RunControl,
        iteration: int,
        emit: EventSink,
        cancellation: RunCancellation,
    ) -> RunResult | None:
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
        self._record_usage_anchor(conversation, response)
        batch = await self._execute_tool_batch(
            conversation,
            completed,
            emit,
            cancellation,
        )
        self._consume_ready_memory_recall(conversation)

        await self._agent._run_hook("turn_end", emit)
        directive = await self._finish_turn(
            control,
            conversation,
            emit,
            iteration,
            would_stop=False,
            hard_stop="terminate" if batch.terminate else None,
        )
        return await self._resolve_turn_directive(directive, iteration, emit)

    async def _execute_tool_batch(
        self,
        conversation: ConversationManager,
        completed: CompletedAssistantMessage,
        emit: EventSink,
        cancellation: RunCancellation,
    ) -> ToolBatchResult:
        batch_request = ToolBatchRequest(
            assistant_message=completed,
            session_dir=self._agent.session_dir,
        )
        try:
            batch = await self._pipeline.execute_batch(
                batch_request,
                emit,
                cancellation,
            )
        except asyncio.CancelledError:
            batch = await self._pipeline.cancelled_batch(
                batch_request,
                self._discard_event,
            )
            conversation.add_tool_results_message(list(batch.messages))
            raise
        conversation.add_tool_results_message(list(batch.messages))
        return batch

    def _consume_ready_memory_recall(
        self,
        conversation: ConversationManager,
    ) -> None:
        agent = self._agent
        if not (
            agent.memory_recall_task
            and not agent._memory_recall_consumed
            and agent.memory_recall_task.done()
        ):
            return
        try:
            recall = agent.memory_recall_task.result()
            if recall:
                conversation.add_system_reminder(recall)
        except Exception:
            log.debug("Memory recall task failed", exc_info=True)
        agent._memory_recall_consumed = True

    async def _resolve_turn_directive(
        self,
        directive: TurnDirective,
        iteration: int,
        emit: EventSink,
    ) -> RunResult | None:
        if directive.continue_run:
            return None
        if directive.reason == "max_turns":
            return await self._max_turn_result(iteration, emit)
        return await self._completed_result(iteration, emit)

    async def _completed_result(
        self,
        iteration: int,
        emit: EventSink,
    ) -> RunResult:
        await emit(LoopComplete(total_turns=iteration))
        return RunResult(
            status="completed",
            turns=iteration,
            final_text=self._last_text,
        )

    @staticmethod
    async def _discard_event(_event: AgentEvent) -> None:
        return None

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
