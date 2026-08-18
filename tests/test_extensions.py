from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from koko_pi_agent.extensions import (
    DuplicateExtensionIdError,
    ExtensionCatalog,
    ExtensionCloseError,
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


def _open_request(
    registry: ToolRegistry,
    *,
    runtime_id: str = "runtime-a",
    profile: ToolProfile = ToolProfile.PROMPT_LEAD,
) -> OpenExtensionSession:
    return OpenExtensionSession(
        context=SessionContext(
            runtime_id=runtime_id,
            generation=1,
            work_dir="/tmp/project",
            profile=profile,
        ),
        registry=registry,
        bindings=object(),
    )


def _single_host(installer, *, critical: bool = True) -> ExtensionHost:
    return ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.resources",
                    display_name="Resource test extension",
                    source="test://resources",
                    installer=installer,
                    critical=critical,
                )
            ]
        )
    )


@pytest.mark.asyncio
async def test_api_owns_resources_and_tasks_with_correct_close_order() -> None:
    order: list[str] = []
    started = asyncio.Event()

    class _Connection:
        def __enter__(self) -> str:
            return "connection"

        def __exit__(self, *exc_info: object) -> None:
            order.append("resource")

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            order.append("task")
            raise

    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("Owned"))
        assert await api.acquire("connection", _Connection()) == "connection"
        api.defer("legacy-shutdown", lambda: order.append("deferred"))
        handle = api.start_task("forever", forever())
        assert handle.name == "forever"
        assert handle.extension_id == "test.resources"
        assert handle.status == "running"

    registry = ToolRegistry()
    session = await _single_host(install).open_session(_open_request(registry))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert registry.get("Owned") is not None

    await session.aclose()

    # contribution 先撤销，然后 task，最后 resource（deferred 后登记故先关）
    assert order == ["task", "deferred", "resource"]
    assert registry.list_contributions() == ()
    assert session.state == "closed"


@pytest.mark.asyncio
async def test_session_close_aggregates_cleanup_failures_and_still_closes() -> None:
    def boom() -> None:
        raise RuntimeError("shutdown exploded")

    cleaned: list[str] = []

    def install(api, _bindings) -> None:
        api.defer("healthy", lambda: cleaned.append("healthy"))
        api.defer("broken", boom)

    registry = ToolRegistry()
    session = await _single_host(install).open_session(_open_request(registry))

    with pytest.raises(ExtensionCloseError) as excinfo:
        await session.aclose()

    assert session.state == "closed"
    assert cleaned == ["healthy"]
    assert [failure.name for failure in excinfo.value.failures] == ["broken"]
    assert "shutdown exploded" in str(excinfo.value)
    assert [
        diagnostic.status
        for diagnostic in session.diagnostics
        if diagnostic.status == "cleanup_failed"
    ] == ["cleanup_failed"]


@pytest.mark.asyncio
async def test_api_rejects_every_registration_after_activation() -> None:
    captured: list[object] = []

    def install(api, _bindings) -> None:
        captured.append(api)

    registry = ToolRegistry()
    session = await _single_host(install).open_session(_open_request(registry))
    api = captured[0]

    with pytest.raises(ExtensionPhaseError):
        api.register_tool(_NamedTool("Late"))
    with pytest.raises(ExtensionPhaseError):
        api.defer("late", lambda: None)
    with pytest.raises(ExtensionPhaseError):
        await api.acquire("late", None)

    late_coroutine = asyncio.sleep(0)
    try:
        with pytest.raises(ExtensionPhaseError):
            api.start_task("late", late_coroutine)
    finally:
        late_coroutine.close()

    await session.aclose()


@pytest.mark.asyncio
async def test_activation_failure_rolls_back_resources_and_tasks() -> None:
    order: list[str] = []
    started = asyncio.Event()

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            order.append("task")
            raise

    async def install(api, _bindings) -> None:
        api.register_tool(_NamedTool("Doomed"))
        api.defer("resource", lambda: order.append("resource"))
        api.start_task("forever", forever())
        await asyncio.wait_for(started.wait(), timeout=1.0)
        raise RuntimeError("installer failed after registering resources")

    registry = ToolRegistry()

    with pytest.raises(ExtensionStartupError):
        await _single_host(install).open_session(_open_request(registry))

    assert order == ["task", "resource"]
    assert registry.list_tools() == []


@pytest.mark.asyncio
async def test_two_sessions_own_separate_resource_scopes() -> None:
    closed: list[str] = []

    def install(api, _bindings) -> None:
        api.defer("resource", lambda: closed.append(api.context.runtime_id))

    host = _single_host(install)
    registry_a = ToolRegistry()
    registry_b = ToolRegistry()
    session_a = await host.open_session(_open_request(registry_a, runtime_id="runtime-a"))
    session_b = await host.open_session(_open_request(registry_b, runtime_id="runtime-b"))

    await session_a.aclose()
    assert closed == ["runtime-a"]
    assert session_b.state == "active"

    await session_b.aclose()
    assert closed == ["runtime-a", "runtime-b"]


@pytest.mark.asyncio
async def test_background_task_failure_is_visible_while_session_is_active() -> None:
    async def explode() -> None:
        raise ValueError("background task exploded")

    def install(api, _bindings) -> None:
        api.start_task("exploding", explode())

    registry = ToolRegistry()
    session = await _single_host(install).open_session(_open_request(registry))

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    failed = [item for item in session.diagnostics if item.status == "task_failed"]
    assert len(failed) == 1
    assert failed[0].name == "exploding"
    assert failed[0].kind == "task"
    assert "background task exploded" in failed[0].error
    # 后台任务失败只让 Runtime degraded，不自动关闭 Session
    assert session.state == "active"

    await session.aclose()
