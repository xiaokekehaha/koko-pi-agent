from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from koko_pi_agent.extensions import (
    DuplicateExtensionIdError,
    ExtensionCatalog,
    ExtensionDefinition,
    ExtensionHost,
    ExtensionPhaseError,
    ExtensionStartupError,
    OpenExtensionSession,
    SessionContext,
    ToolProfile,
)
from koko_pi_agent.tools import ToolConflictError, ToolRegistry
from koko_pi_agent.tools.base import Tool, ToolResult


class _Params(BaseModel):
    pass


class _NamedTool(Tool):
    description = "extension test tool"
    params_model = _Params

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, params: _Params) -> ToolResult:
        return ToolResult(output=self.name)


@pytest.mark.asyncio
async def test_open_session_activates_tools_and_close_reverses_ownership() -> None:
    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("First"))
        api.register_tool(_NamedTool("Second"))

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.tools",
                    display_name="Test tools",
                    source="test://tools",
                    installer=install,
                )
            ]
        )
    )
    registry = ToolRegistry()

    session = await host.open_session(
        OpenExtensionSession(
            context=SessionContext(
                runtime_id="runtime-a",
                generation=1,
                work_dir="/tmp/project",
                profile=ToolProfile.PROMPT_LEAD,
            ),
            registry=registry,
            bindings=object(),
        )
    )

    assert session.registry is registry
    assert [tool.name for tool in registry.list_tools()] == ["First", "Second"]
    assert [(item.extension_id, item.status) for item in session.diagnostics] == [
        ("test.tools", "activated")
    ]

    await session.aclose()
    await session.aclose()

    assert registry.list_tools() == []


@pytest.mark.asyncio
async def test_session_close_runs_all_callbacks_when_one_handle_fails() -> None:
    class FailingHandle:
        def __init__(self, handle) -> None:
            self._handle = handle

        def close(self) -> None:
            self._handle.close()
            raise RuntimeError("close failed")

    class FailingRegistry(ToolRegistry):
        def register(self, tool, *, owner=None):
            handle = super().register(tool, owner=owner)
            if tool.name == "Failing":
                return FailingHandle(handle)
            return handle

    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("Failing"))
        api.register_tool(_NamedTool("Other"))

    registry = FailingRegistry()
    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.close-failure",
                    display_name="Close failure",
                    source="test://close-failure",
                    installer=install,
                )
            ]
        )
    )
    session = await host.open_session(
        OpenExtensionSession(
            context=SessionContext(
                runtime_id="runtime-a",
                generation=1,
                work_dir="/tmp/project",
                profile=ToolProfile.PROMPT_LEAD,
            ),
            registry=registry,
            bindings=object(),
        )
    )

    with pytest.raises(RuntimeError, match="close failed"):
        await session.aclose()

    assert session.state == "closed"
    assert registry.list_contributions() == ()
    await session.aclose()
    assert session.state == "closed"


@pytest.mark.asyncio
async def test_startup_failure_rolls_back_partial_extension_registration() -> None:
    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("First"))
        api.register_tool(_NamedTool("Existing"))

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.failing",
                    display_name="Failing tools",
                    source="test://failing",
                    installer=install,
                )
            ]
        )
    )
    registry = ToolRegistry()
    existing = _NamedTool("Existing")
    registry.register(existing)

    with pytest.raises(ExtensionStartupError) as captured:
        await host.open_session(
            OpenExtensionSession(
                context=SessionContext(
                    runtime_id="runtime-a",
                    generation=1,
                    work_dir="/tmp/project",
                    profile=ToolProfile.PROMPT_LEAD,
                ),
                registry=registry,
                bindings=object(),
            )
        )

    assert isinstance(captured.value.cause, ToolConflictError)
    assert [tool.name for tool in registry.list_tools()] == ["Existing"]
    assert registry.get("Existing") is existing
    assert [
        (item.extension_id, item.status) for item in captured.value.diagnostics
    ] == [("test.failing", "failed")]


@pytest.mark.asyncio
async def test_critical_failure_closes_previously_activated_extensions() -> None:
    async def install_first(api, _bindings) -> None:
        api.register_tool(_NamedTool("First"))

    async def install_failing(api, _bindings) -> None:
        api.register_tool(_NamedTool("Second"))
        raise RuntimeError("activation failed")

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.first",
                    display_name="First",
                    source="test://first",
                    installer=install_first,
                ),
                ExtensionDefinition(
                    extension_id="test.failing",
                    display_name="Failing",
                    source="test://failing",
                    installer=install_failing,
                ),
            ]
        )
    )
    registry = ToolRegistry()

    with pytest.raises(ExtensionStartupError) as captured:
        await host.open_session(
            OpenExtensionSession(
                context=SessionContext(
                    runtime_id="runtime-a",
                    generation=1,
                    work_dir="/tmp/project",
                    profile=ToolProfile.PROMPT_LEAD,
                ),
                registry=registry,
                bindings=object(),
            )
        )

    assert registry.list_tools() == []
    assert [
        (item.extension_id, item.status) for item in captured.value.diagnostics
    ] == [
        ("test.first", "activated"),
        ("test.failing", "failed"),
    ]


@pytest.mark.asyncio
async def test_noncritical_failure_isolated_and_active_api_is_sealed() -> None:
    captured_api = None

    async def install_noncritical(api, _bindings) -> None:
        api.register_tool(_NamedTool("Temporary"))
        raise RuntimeError("optional failed")

    async def install_good(api, _bindings) -> None:
        nonlocal captured_api
        captured_api = api
        api.register_tool(_NamedTool("Good"))

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.optional",
                    display_name="Optional",
                    source="test://optional",
                    installer=install_noncritical,
                    critical=False,
                ),
                ExtensionDefinition(
                    extension_id="test.good",
                    display_name="Good",
                    source="test://good",
                    installer=install_good,
                ),
            ]
        )
    )
    registry = ToolRegistry()
    session = await host.open_session(
        OpenExtensionSession(
            context=SessionContext(
                runtime_id="runtime-a",
                generation=1,
                work_dir="/tmp/project",
                profile=ToolProfile.PROMPT_LEAD,
            ),
            registry=registry,
            bindings=object(),
        )
    )

    assert [tool.name for tool in registry.list_tools()] == ["Good"]
    assert [(item.extension_id, item.status) for item in session.diagnostics] == [
        ("test.optional", "failed"),
        ("test.good", "activated"),
    ]
    assert captured_api is not None
    with pytest.raises(ExtensionPhaseError, match="active"):
        captured_api.register_tool(_NamedTool("Late"))

    await session.aclose()

    with pytest.raises(ExtensionPhaseError, match="closed"):
        captured_api.register_tool(_NamedTool("Later"))


def test_catalog_rejects_duplicate_extension_ids() -> None:
    async def install(_api, _bindings) -> None:
        return None

    definition = ExtensionDefinition(
        extension_id="test.duplicate",
        display_name="Duplicate",
        source="test://duplicate",
        installer=install,
    )

    with pytest.raises(DuplicateExtensionIdError, match="test.duplicate"):
        ExtensionCatalog([definition, definition])


@pytest.mark.asyncio
async def test_cancelled_activation_rolls_back_and_preserves_cancellation() -> None:
    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("Temporary"))
        raise asyncio.CancelledError

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.cancelled",
                    display_name="Cancelled",
                    source="test://cancelled",
                    installer=install,
                    critical=False,
                )
            ]
        )
    )
    registry = ToolRegistry()

    with pytest.raises(asyncio.CancelledError):
        await host.open_session(
            OpenExtensionSession(
                context=SessionContext(
                    runtime_id="runtime-a",
                    generation=1,
                    work_dir="/tmp/project",
                    profile=ToolProfile.PROMPT_LEAD,
                ),
                registry=registry,
                bindings=object(),
            )
        )

    assert registry.list_tools() == []
