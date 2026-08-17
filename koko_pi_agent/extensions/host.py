from __future__ import annotations

import inspect
from contextlib import AsyncExitStack

from koko_pi_agent.extensions.contracts import (
    DuplicateExtensionIdError,
    ExtensionDefinition,
    ExtensionDiagnostic,
    ExtensionPhaseError,
    ExtensionStartupError,
    OpenExtensionSession,
    SessionContext,
    ToolProfile,
)
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
    def __init__(
        self,
        *,
        definition: ExtensionDefinition,
        context: SessionContext,
        registry: ToolRegistry,
        scope: AsyncExitStack,
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
        if self._state != "activating":
            raise ExtensionPhaseError(
                f"Extension '{self._definition.extension_id}' cannot register tools "
                f"while {self._state}"
            )
        handle = self._registry.register(
            tool,
            owner=ContributionOwner(
                extension_id=self._definition.extension_id,
                source=self._definition.source,
                runtime_id=self._context.runtime_id,
                generation=self._context.generation,
            ),
        )
        self._scope.callback(handle.close)
        return handle

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
        scope: AsyncExitStack,
        apis: list[ExtensionAPI],
    ) -> None:
        self._registry = registry
        self._diagnostics = diagnostics
        self._scope = scope
        self._apis = apis
        self._state = "active"

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def diagnostics(self) -> tuple[ExtensionDiagnostic, ...]:
        return tuple(self._diagnostics)

    @property
    def state(self) -> str:
        return self._state

    async def aclose(self) -> None:
        if self._state == "closed":
            return
        self._state = "closing"
        for api in self._apis:
            api._close()
        try:
            await self._scope.aclose()
        finally:
            self._state = "closed"


class ExtensionHost:
    def __init__(self, catalog: ExtensionCatalog) -> None:
        self._catalog = catalog

    async def open_session(self, request: OpenExtensionSession) -> ExtensionSession:
        session_scope = AsyncExitStack()
        diagnostics: list[ExtensionDiagnostic] = []
        apis: list[ExtensionAPI] = []

        for definition in self._catalog.definitions_for(request.context.profile):
            extension_scope = AsyncExitStack()
            api = ExtensionAPI(
                definition=definition,
                context=request.context,
                registry=request.registry,
                scope=extension_scope,
            )
            try:
                result = definition.installer(api, request.bindings)
                if inspect.isawaitable(result):
                    await result
            except BaseException as error:
                api._close()
                await extension_scope.aclose()
                if not isinstance(error, Exception):
                    for active_api in apis:
                        active_api._close()
                    await session_scope.aclose()
                    raise
                diagnostics.append(
                    ExtensionDiagnostic(
                        extension_id=definition.extension_id,
                        source=definition.source,
                        status="failed",
                        error=str(error),
                    )
                )
                if definition.critical:
                    for active_api in apis:
                        active_api._close()
                    await session_scope.aclose()
                    raise ExtensionStartupError(
                        definition.extension_id,
                        error,
                        tuple(diagnostics),
                    ) from error
                continue

            api._finish_activation()
            apis.append(api)
            session_scope.push_async_callback(extension_scope.aclose)
            diagnostics.append(
                ExtensionDiagnostic(
                    extension_id=definition.extension_id,
                    source=definition.source,
                    status="activated",
                )
            )

        return ExtensionSession(
            registry=request.registry,
            diagnostics=diagnostics,
            scope=session_scope,
            apis=apis,
        )
