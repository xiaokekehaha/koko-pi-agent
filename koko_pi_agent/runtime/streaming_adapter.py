from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from koko_pi_agent.runtime.agent_run import AgentRun, RunStatus
from koko_pi_agent.runtime.events import AgentEvent, RunFinished


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
