from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import Any

from koko_pi_agent.extensions.contracts import (
    DuplicateExtensionIdError,
    ExtensionCleanupFailure,
    ExtensionCloseError,
    ExtensionDefinition,
    ExtensionDiagnostic,
    ExtensionPhaseError,
    ExtensionStartupError,
    ExtensionTaskHandle,
    OpenExtensionSession,
    SessionContext,
    ToolProfile,
)
from koko_pi_agent.extensions.resources import CleanupCallable, ResourceScope
from koko_pi_agent.tools import ContributionOwner, RegistrationHandle, ToolRegistry
from koko_pi_agent.tools.base import Tool


class ExtensionCatalog:
    def __init__(self, definitions: list[ExtensionDefinition]) -> None:
        seen: set[str] = set()
        for definition in definitions:
            if definition.extension_id in seen:
                raise DuplicateExtensionIdError(definition.extension_id)
            seen.add(definition.extension_id)
        self._definitions = tuple(definitions)

    def definitions_for(self, profile: ToolProfile) -> tuple[ExtensionDefinition, ...]:
        return tuple(
            definition
            for definition in self._definitions
            if definition.profiles is None or profile in definition.profiles
        )


class ExtensionAPI:
    """扩展唯一可以使用的窗口。

    四个登记方法共用同一个 activating-only 相位守卫：Session 进入 active 后不再
    接受动态登记，避免在 reload 语义确定之前引入 stale API。
    """

    def __init__(
        self,
        *,
        definition: ExtensionDefinition,
        context: SessionContext,
        registry: ToolRegistry,
        scope: ResourceScope,
    ) -> None:
        self._definition = definition
        self._context = context
        self._registry = registry
        self._scope = scope
        self._state = "activating"

    @property
    def context(self) -> SessionContext:
        return self._context

    def register_tool(self, tool: Tool) -> RegistrationHandle:
        self._ensure_activating("register tools")
        handle = self._registry.register(
            tool,
            owner=ContributionOwner(
                extension_id=self._definition.extension_id,
                source=self._definition.source,
                runtime_id=self._context.runtime_id,
                generation=self._context.generation,
            ),
        )
        self._scope.add_contribution(tool.name, handle.close)
        return handle

    async def acquire(self, name: str, manager: Any) -> Any:
        """接管一个同步或异步 context manager，关闭由 Runtime 负责。"""

        self._ensure_activating("acquire resources")
        return await self._scope.acquire(name, manager)

    def defer(self, name: str, cleanup: CleanupCallable) -> None:
        """接管一个没有 context-manager Interface 的旧资源的清理动作。"""

        self._ensure_activating("defer cleanup")
        self._scope.defer(name, cleanup)

    def start_task(self, name: str, awaitable: Awaitable[None]) -> ExtensionTaskHandle:
        """启动一个由本扩展拥有的长生命周期任务。

        启动不等于 readiness：需要就绪才能继续的扩展必须在 installer 返回前显式
        await，本方法之后的异步失败只让 Runtime degraded。
        """

        self._ensure_activating("start tasks")
        return self._scope.start_task(name, awaitable)

    def _ensure_activating(self, action: str) -> None:
        if self._state != "activating":
            raise ExtensionPhaseError(
                f"Extension '{self._definition.extension_id}' cannot {action} "
                f"while {self._state}"
            )

    def _finish_activation(self) -> None:
        self._state = "active"

    def _close(self) -> None:
        self._state = "closed"


class ExtensionSession:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        diagnostics: list[ExtensionDiagnostic],
        scopes: list[ResourceScope],
        apis: list[ExtensionAPI],
    ) -> None:
        self._registry = registry
        self._diagnostics = diagnostics
        self._scopes = scopes
        self._apis = apis
        self._state = "active"
        self._close_lock = asyncio.Lock()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def diagnostics(self) -> tuple[ExtensionDiagnostic, ...]:
        """生命周期内持续更新的只读快照，后台任务失败在运行期即可见。"""

        return tuple(self._diagnostics)

    @property
    def state(self) -> str:
        return self._state

    async def aclose(self) -> None:
        """按 extension 激活逆序关闭。

        每个 scope 都会被关闭，一个失败不阻止其余；全部结束后才用一个聚合
        ExtensionCloseError 报告，此时 state 已经是 closed。
        """

        if self._state == "closed":
            return
        async with self._close_lock:
            if self._state == "closed":
                return
            self._state = "closing"
            for api in self._apis:
                api._close()
            failures: list[ExtensionCleanupFailure] = []
            try:
                for scope in reversed(self._scopes):
                    failures.extend(await scope.aclose())
            finally:
                self._state = "closed"
            if failures:
                raise ExtensionCloseError(tuple(failures))


class ExtensionHost:
    def __init__(self, catalog: ExtensionCatalog) -> None:
        self._catalog = catalog

    async def open_session(self, request: OpenExtensionSession) -> ExtensionSession:
        diagnostics: list[ExtensionDiagnostic] = []
        apis: list[ExtensionAPI] = []
        scopes: list[ResourceScope] = []

        for definition in self._catalog.definitions_for(request.context.profile):
            scope = ResourceScope(
                extension_id=definition.extension_id,
                source=definition.source,
                diagnostics=diagnostics.append,
            )
            api = ExtensionAPI(
                definition=definition,
                context=request.context,
                registry=request.registry,
                scope=scope,
            )
            try:
                result = definition.installer(api, request.bindings)
                if inspect.isawaitable(result):
                    await result
            except BaseException as error:
                api._close()
                # 回滚本 extension 已登记的一切。清理失败通过 sink 进诊断，
                # 绝不遮蔽 installer 的原始异常。
                await scope.aclose()
                if not isinstance(error, Exception):
                    await self._close_activated(apis, scopes)
                    raise
                diagnostics.append(
                    ExtensionDiagnostic(
                        extension_id=definition.extension_id,
                        source=definition.source,
                        status="failed",
                        error=str(error),
                        phase="activating",
                    )
                )
                if definition.critical:
                    await self._close_activated(apis, scopes)
                    raise ExtensionStartupError(
                        definition.extension_id,
                        error,
                        tuple(diagnostics),
                    ) from error
                continue

            api._finish_activation()
            apis.append(api)
            scopes.append(scope)
            diagnostics.append(
                ExtensionDiagnostic(
                    extension_id=definition.extension_id,
                    source=definition.source,
                    status="activated",
                    phase="activating",
                )
            )

        return ExtensionSession(
            registry=request.registry,
            diagnostics=diagnostics,
            scopes=scopes,
            apis=apis,
        )

    @staticmethod
    async def _close_activated(
        apis: list[ExtensionAPI],
        scopes: list[ResourceScope],
    ) -> None:
        for api in apis:
            api._close()
        for scope in reversed(scopes):
            await scope.aclose()
