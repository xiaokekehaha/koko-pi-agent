from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from koko_pi_agent.context import apply_tool_result_budget, is_spill_readback
from koko_pi_agent.context.manager import make_persisted_preview, persist_tool_result
from koko_pi_agent.conversation import ToolResultBlock
from koko_pi_agent.conversation_pairing import REJECTED_TOOL_RESULT
from koko_pi_agent.hooks import HookContext, HookEngine
from koko_pi_agent.permissions import PermissionChecker, PermissionMode
from koko_pi_agent.permissions.rules import Rule, extract_content
from koko_pi_agent.runtime.events import (
    EventSink,
    HookEvent,
    PermissionRequest,
    PermissionResponse,
    ToolExecutionStarted,
    ToolResultEvent,
)
from koko_pi_agent.tools import ToolRegistry
from koko_pi_agent.tools.base import MAX_OUTPUT_CHARS, Tool, ToolCallComplete, ToolResult

TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "length"})


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class ApprovalAdapter(Protocol):
    async def approve(
        self,
        tool_name: str,
        description: str,
        emit: EventSink,
    ) -> PermissionResponse: ...


class InteractiveApprovalAdapter:
    async def approve(
        self,
        tool_name: str,
        description: str,
        emit: EventSink,
    ) -> PermissionResponse:
        future: asyncio.Future[PermissionResponse] = (
            asyncio.get_running_loop().create_future()
        )
        await emit(
            PermissionRequest(
                tool_name=tool_name,
                description=description,
                future=future,
            )
        )
        return await future


class HeadlessApprovalAdapter:
    def __init__(self, permission_mode: PermissionMode) -> None:
        self._permission_mode = permission_mode

    async def approve(
        self,
        tool_name: str,
        description: str,
        emit: EventSink,
    ) -> PermissionResponse:
        if self._permission_mode == PermissionMode.BYPASS:
            return PermissionResponse.ALLOW
        return PermissionResponse.DENY


@dataclass(frozen=True)
class CompletedAssistantMessage:
    text: str
    tool_calls: tuple[ToolCallComplete, ...]
    stop_reason: str

    @property
    def is_truncated(self) -> bool:
        return self.stop_reason in TRUNCATED_STOP_REASONS


@dataclass(frozen=True)
class ToolBatchRequest:
    assistant_message: CompletedAssistantMessage
    session_dir: Path


@dataclass(frozen=True)
class ToolBatchResult:
    messages: tuple[ToolResultBlock, ...]
    terminate: bool


@dataclass(frozen=True)
class _PreparedToolCall:
    index: int
    call: ToolCallComplete
    tool: Tool
    params: BaseModel


@dataclass(frozen=True)
class _Execution:
    index: int
    call: ToolCallComplete
    result: ToolResult
    elapsed: float
    executed: bool


class ToolPipeline:
    """The only path from a completed model tool batch to conversation results."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        permission_checker: PermissionChecker | None = None,
        approval: ApprovalAdapter | None = None,
        hook_engine: HookEngine | None = None,
        recovery_state: Any = None,
    ) -> None:
        self._registry = registry
        self._permission_checker = permission_checker
        self._approval = approval or HeadlessApprovalAdapter(PermissionMode.DEFAULT)
        self._hook_engine = hook_engine
        self._recovery_state = recovery_state

    async def execute_batch(
        self,
        request: ToolBatchRequest,
        emit: EventSink,
        cancellation: CancellationToken,
    ) -> ToolBatchResult:
        message = request.assistant_message
        calls = list(message.tool_calls)
        if message.is_truncated:
            executions = [
                self._error_execution(
                    index,
                    call,
                    "Tool call was not executed because the assistant response was "
                    "truncated. Reissue the complete tool call.",
                )
                for index, call in enumerate(calls)
            ]
            return await self._finish_batch(executions, request, emit)

        prepared: list[_PreparedToolCall | _Execution] = []
        for index, call in enumerate(calls):
            cancellation.raise_if_cancelled()
            prepared.append(await self._prepare(index, call, emit))

        executions: list[_Execution] = []
        concurrent_group: list[_PreparedToolCall] = []

        async def flush_concurrent() -> None:
            if not concurrent_group:
                return
            executions.extend(
                await self._execute_concurrent(
                    list(concurrent_group), emit, cancellation
                )
            )
            concurrent_group.clear()

        for item in prepared:
            cancellation.raise_if_cancelled()
            if isinstance(item, _Execution):
                await flush_concurrent()
                executions.append(item)
                continue
            if item.tool.is_concurrency_safe:
                concurrent_group.append(item)
                continue
            await flush_concurrent()
            execution = await self._execute_one(item, emit, cancellation)
            execution = await self._finalize_execution(execution)
            executions.append(execution)
            await self._emit_result(execution, emit)

        await flush_concurrent()
        return await self._finish_batch(executions, request, emit)

    async def cancelled_batch(
        self,
        request: ToolBatchRequest,
        emit: EventSink,
    ) -> ToolBatchResult:
        executions = [
            self._error_execution(index, call, "Tool execution cancelled")
            for index, call in enumerate(request.assistant_message.tool_calls)
        ]
        return await self._finish_batch(executions, request, emit)

    async def _prepare(
        self,
        index: int,
        call: ToolCallComplete,
        emit: EventSink,
    ) -> _PreparedToolCall | _Execution:
        tool = self._registry.get(call.tool_name)
        if tool is None:
            return self._error_execution(
                index, call, f"Error: unknown tool '{call.tool_name}'"
            )
        if not self._registry.is_enabled(call.tool_name):
            return self._error_execution(
                index, call, f"Error: tool '{call.tool_name}' is disabled"
            )

        try:
            params = tool.params_model.model_validate(call.arguments)
        except ValidationError as exc:
            return self._error_execution(
                index, call, f"Parameter validation error: {exc}"
            )

        if self._hook_engine is not None:
            context = self._hook_context("pre_tool_use", call)
            try:
                rejection = await self._hook_engine.run_pre_tool_hooks(context)
                await self._emit_hook_notifications(emit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - hooks fail as values
                return self._error_execution(index, call, f"Pre-tool hook error: {exc}")
            if rejection is not None:
                return self._error_execution(
                    index, call, f"Hook rejected: {rejection.reason}"
                )

        if self._permission_checker is not None:
            try:
                decision = self._permission_checker.check(tool, call.arguments)
            except Exception as exc:  # noqa: BLE001 - permission is a boundary
                return self._error_execution(
                    index, call, f"Permission check error: {exc}"
                )
            if decision.effect == "deny":
                return self._error_execution(
                    index, call, f"Permission denied: {decision.reason}"
                )
            if decision.effect == "ask":
                description = PermissionChecker.describe_tool_action(
                    call.tool_name, call.arguments
                )
                try:
                    response = await self._approval.approve(
                        call.tool_name, description, emit
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - approval is a boundary
                    return self._error_execution(
                        index, call, f"Permission approval error: {exc}"
                    )
                if response == PermissionResponse.DENY:
                    return self._error_execution(index, call, REJECTED_TOOL_RESULT)
                if response == PermissionResponse.ALLOW_ALWAYS:
                    try:
                        self._remember_approval(call)
                    except Exception as exc:  # noqa: BLE001 - persistence boundary
                        return self._error_execution(
                            index,
                            call,
                            f"Permission approval persistence error: {exc}",
                        )

        return _PreparedToolCall(index=index, call=call, tool=tool, params=params)

    async def _execute_concurrent(
        self,
        group: list[_PreparedToolCall],
        emit: EventSink,
        cancellation: CancellationToken,
    ) -> list[_Execution]:
        completion_queue: asyncio.Queue[_Execution] = asyncio.Queue()

        async def execute_and_report(item: _PreparedToolCall) -> None:
            result = await self._execute_one(
                item, emit, cancellation, emit_started=False
            )
            await completion_queue.put(result)

        completed: list[_Execution] = []
        for item in group:
            cancellation.raise_if_cancelled()
            await emit(
                ToolExecutionStarted(
                    tool_id=item.call.tool_id,
                    tool_name=item.call.tool_name,
                )
            )
        async with asyncio.TaskGroup() as task_group:
            for item in group:
                cancellation.raise_if_cancelled()
                task_group.create_task(execute_and_report(item))
            for _ in group:
                execution = await completion_queue.get()
                execution = await self._finalize_execution(execution)
                completed.append(execution)
                await self._emit_result(execution, emit)
        return completed

    async def _execute_one(
        self,
        item: _PreparedToolCall,
        emit: EventSink,
        cancellation: CancellationToken,
        *,
        emit_started: bool = True,
    ) -> _Execution:
        cancellation.raise_if_cancelled()
        if emit_started:
            await emit(
                ToolExecutionStarted(
                    tool_id=item.call.tool_id,
                    tool_name=item.call.tool_name,
                )
            )
        start = time.monotonic()
        try:
            result = await item.tool.execute(item.params)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - tools report failures as values
            result = ToolResult(output=f"Tool execution error: {exc}", is_error=True)
        return _Execution(
            index=item.index,
            call=item.call,
            result=result,
            elapsed=time.monotonic() - start,
            executed=True,
        )

    async def _finalize_execution(self, execution: _Execution) -> _Execution:
        if self._hook_engine is not None:
            try:
                await self._hook_engine.run_hooks(
                    "post_tool_use",
                    self._hook_context("post_tool_use", execution.call),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - hooks fail as values
                execution = replace(
                    execution,
                    result=ToolResult(
                        output=(
                            f"{execution.result.output}\n\nPost-tool hook error: {exc}"
                        ),
                        is_error=True,
                        terminate=execution.result.terminate,
                    ),
                )
        self._snapshot_for_recovery(execution.call, execution.result)
        return execution

    async def _finish_batch(
        self,
        executions: list[_Execution],
        request: ToolBatchRequest,
        emit: EventSink,
    ) -> ToolBatchResult:
        by_index = sorted(executions, key=lambda item: item.index)
        emitted = {item.index for item in executions if item.executed}
        for execution in by_index:
            if execution.index not in emitted:
                await self._emit_result(execution, emit)

        exempt_ids = {
            call.tool_id
            for call in request.assistant_message.tool_calls
            if is_spill_readback(call.tool_name, call.arguments, request.session_dir)
        }
        messages = [
            ToolResultBlock(
                tool_use_id=execution.call.tool_id,
                content=self._persist_or_truncate(
                    execution.call.tool_id,
                    execution.result.output,
                    request.session_dir,
                    exempt_ids,
                ),
                is_error=execution.result.is_error,
            )
            for execution in by_index
        ]
        apply_tool_result_budget(messages, request.session_dir, exempt_ids)
        return ToolBatchResult(
            messages=tuple(messages),
            terminate=any(execution.result.terminate for execution in by_index),
        )

    async def _emit_result(self, execution: _Execution, emit: EventSink) -> None:
        await self._emit_hook_notifications(emit)
        await emit(
            ToolResultEvent(
                tool_id=execution.call.tool_id,
                tool_name=execution.call.tool_name,
                output=execution.result.output,
                is_error=execution.result.is_error,
                elapsed=execution.elapsed,
            )
        )

    async def _emit_hook_notifications(self, emit: EventSink) -> None:
        if self._hook_engine is None:
            return
        for notification in self._hook_engine.drain_notifications():
            await emit(
                HookEvent(
                    hook_id=notification.hook_id,
                    event=notification.event,
                    output=notification.output,
                    success=notification.success,
                )
            )

    def _remember_approval(self, call: ToolCallComplete) -> None:
        if self._permission_checker is None:
            return
        content = extract_content(call.tool_name, call.arguments)
        pattern = f"{content[:60]}*" if len(content) > 60 else f"{content}*"
        self._permission_checker.rule_engine.append_local_rule(
            Rule(tool_name=call.tool_name, pattern=pattern, effect="allow")
        )
        self._permission_checker.add_session_allow(call.tool_name, content)

    def _hook_context(self, event_name: str, call: ToolCallComplete) -> HookContext:
        file_path = str(call.arguments.get("file_path", call.arguments.get("path", "")))
        return HookContext(
            event_name=event_name,
            tool_name=call.tool_name,
            tool_args=call.arguments,
            file_path=file_path,
        )

    def _snapshot_for_recovery(
        self, call: ToolCallComplete, result: ToolResult
    ) -> None:
        if (
            self._recovery_state is None
            or result.is_error
            or call.tool_name != "ReadFile"
        ):
            return
        path = call.arguments.get("file_path")
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._recovery_state.record_file_read(path, content)

    @staticmethod
    def _persist_or_truncate(
        tool_use_id: str,
        text: str,
        session_dir: Path,
        exempt_ids: set[str],
    ) -> str:
        if tool_use_id in exempt_ids or len(text) <= MAX_OUTPUT_CHARS:
            return text
        try:
            path = persist_tool_result(tool_use_id, text, session_dir)
        except OSError:
            exempt_ids.add(tool_use_id)
            return text
        exempt_ids.add(tool_use_id)
        return make_persisted_preview(text, path)

    @staticmethod
    def _error_execution(
        index: int,
        call: ToolCallComplete,
        message: str,
    ) -> _Execution:
        return _Execution(
            index=index,
            call=call,
            result=ToolResult(output=message, is_error=True),
            elapsed=0.0,
            executed=False,
        )
