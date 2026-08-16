from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mewcode.extensions import (
    ExtensionDiagnostic,
    ExtensionHost,
    OpenExtensionSession,
    SessionContext,
    ToolProfile,
)
from mewcode.extensions.host import ExtensionSession
from mewcode.runtime.run_control import RunInputReceipt
from mewcode.tools import ToolRegistry, ToolView

AgentFactory = Callable[[ToolRegistry], Any]
BindingsFactory = Callable[[Any, ToolRegistry], Any]


@dataclass(frozen=True)
class AgentRuntimeRequest:
    profile: ToolProfile
    work_dir: str
    agent_factory: AgentFactory
    bindings_factory: BindingsFactory
    runtime_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    generation: int = 1


class AgentRuntime:
    def __init__(
        self,
        *,
        agent: Any,
        registry: ToolRegistry,
        session: ExtensionSession,
    ) -> None:
        self._agent = agent
        self._registry = registry
        self._session = session
        self._diagnostics = list(session.diagnostics)
        self._state = "active"
        self._close_lock = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        request: AgentRuntimeRequest,
        *,
        extension_host: ExtensionHost,
    ) -> AgentRuntime:
        registry = ToolRegistry()
        agent = request.agent_factory(registry)
        if getattr(agent, "registry", None) is not registry:
            raise ValueError("Agent factory must attach the runtime ToolRegistry")
        bindings = request.bindings_factory(agent, registry)
        session = await extension_host.open_session(
            OpenExtensionSession(
                context=SessionContext(
                    runtime_id=request.runtime_id,
                    generation=request.generation,
                    work_dir=request.work_dir,
                    profile=request.profile,
                ),
                registry=registry,
                bindings=bindings,
            )
        )
        return cls(agent=agent, registry=registry, session=session)

    @property
    def agent(self) -> Any:
        return self._agent

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def diagnostics(self) -> tuple[ExtensionDiagnostic, ...]:
        return tuple(self._diagnostics)

    @property
    def state(self) -> str:
        return self._state

    def start_run(self, *args: Any, **kwargs: Any) -> Any:
        if self._state != "active":
            raise RuntimeError(f"AgentRuntime is {self._state}")
        return self._agent.start_run(*args, **kwargs)

    def steer_active_run(self, text: str) -> RunInputReceipt | None:
        if self._state != "active":
            raise RuntimeError(f"AgentRuntime is {self._state}")
        active_run = self._agent.active_run
        if active_run is None:
            return None
        return active_run.steer(text)

    def follow_up_active_run(self, text: str) -> RunInputReceipt | None:
        if self._state != "active":
            raise RuntimeError(f"AgentRuntime is {self._state}")
        active_run = self._agent.active_run
        if active_run is None:
            return None
        return active_run.follow_up(text)

    def cancel_active_run(self) -> bool:
        if self._state != "active":
            raise RuntimeError(f"AgentRuntime is {self._state}")
        if self._agent.active_run is None:
            return False
        self._agent.cancel_active_run()
        return True

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._state == "closed":
                return
            self._state = "closing"
            active_run = self._agent.active_run
            if active_run is not None:
                self._agent.cancel_active_run()
            try:
                if active_run is not None:
                    await active_run.wait_until_idle()
            finally:
                try:
                    visible_registry = getattr(self._agent, "registry", None)
                    if isinstance(visible_registry, ToolView):
                        visible_registry.close()
                        self._agent.registry = self._registry
                    await self._session.aclose()
                finally:
                    for contribution in self._registry.list_contributions():
                        self._diagnostics.append(
                            ExtensionDiagnostic(
                                extension_id=contribution.owner.extension_id,
                                source=contribution.owner.source,
                                status="leaked",
                                error=(
                                    f"Tool '{contribution.name}' remained registered "
                                    "after AgentRuntime close"
                                ),
                            )
                        )
                    self._state = "closed"

    async def __aenter__(self) -> AgentRuntime:
        if self._state != "active":
            raise RuntimeError(f"AgentRuntime is {self._state}")
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
