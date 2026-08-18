from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from koko_pi_agent.agents.loader import AgentLoader
from koko_pi_agent.agents.task_manager import TaskManager
from koko_pi_agent.agents.trace import TraceManager
from koko_pi_agent.client import LLMClient
from koko_pi_agent.config import AppConfig, ProviderConfig
from koko_pi_agent.extensions import (
    BuiltinRuntimeBindings,
    ExtensionCatalog,
    ExtensionDefinition,
    ExtensionHost,
    ExtensionStartupError,
    RuntimeProfile,
    ToolProfile,
    create_builtin_extension_host,
    tool_names_for_profile,
)
from koko_pi_agent.permissions import PermissionMode
from koko_pi_agent.runtime import AgentRuntime, AgentRuntimeRequest
from koko_pi_agent.skills.loader import SkillLoader
from koko_pi_agent.teams.manager import TeamManager
from koko_pi_agent.tools import ToolView
from koko_pi_agent.tools.base import StreamEnd, TextDelta, Tool, ToolResult
from koko_pi_agent.worktree import WorktreeManager


class _OwnedTool(Tool):
    name = "Owned"
    description = "owned by the runtime session"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(output="ok")


@dataclass
class _FakeRun:
    cancelled: bool = False
    waited: bool = False
    queued: list[tuple[str, str]] | None = None

    def steer(self, text: str):
        if self.queued is None:
            self.queued = []
        receipt = ("steering", text)
        self.queued.append(receipt)
        return receipt

    def follow_up(self, text: str):
        if self.queued is None:
            self.queued = []
        receipt = ("follow_up", text)
        self.queued.append(receipt)
        return receipt

    def cancel(self) -> None:
        self.cancelled = True

    async def wait_until_idle(self) -> None:
        self.waited = True


class _FakeAgent:
    def __init__(self, registry) -> None:
        self.registry = registry
        self.active_run: _FakeRun | None = None
        self.started_with: tuple[object, object, object] | None = None

    def start_run(self, conversation, emit, *, approval=None):
        self.started_with = (conversation, emit, approval)
        self.active_run = _FakeRun()
        return self.active_run

    def cancel_active_run(self) -> None:
        if self.active_run is not None:
            self.active_run.cancel()


class _PromptClient(LLMClient):
    async def stream(self, conversation, system="", tools=None):
        yield TextDelta(text="prompt-ok")
        yield StreamEnd(stop_reason="end_turn", input_tokens=2, output_tokens=1)


@pytest.mark.parametrize(
    ("profile", "expected_names"),
    [
        (
            ToolProfile.TUI_LEAD,
            (
                "ReadFile",
                "WriteFile",
                "EditFile",
                "Bash",
                "Glob",
                "Grep",
                "LoadSkill",
                "InstallSkill",
                "ToolSearch",
                "AskUserQuestion",
                "ExitPlanMode",
                "EnterWorktree",
                "ExitWorktree",
                "Agent",
                "TeamCreate",
                "TeamDelete",
                "SyntheticOutput",
                "TaskStop",
            ),
        ),
        (
            ToolProfile.PROMPT_LEAD,
            (
                "ReadFile",
                "WriteFile",
                "EditFile",
                "Bash",
                "Glob",
                "Grep",
                "ToolSearch",
                "Agent",
                "TeamCreate",
                "TeamDelete",
                "SyntheticOutput",
                "TaskStop",
            ),
        ),
        (
            ToolProfile.REMOTE_LEAD,
            (
                "ReadFile",
                "WriteFile",
                "EditFile",
                "Bash",
                "Glob",
                "Grep",
                "ToolSearch",
                "LoadSkill",
                "Agent",
                "TeamCreate",
                "TeamDelete",
                "TaskStop",
                "SyntheticOutput",
            ),
        ),
        (
            ToolProfile.TEAMMATE_WORKER,
            (
                "ReadFile",
                "WriteFile",
                "EditFile",
                "Bash",
                "Glob",
                "Grep",
                "ToolSearch",
                "SyntheticOutput",
                "EnterWorktree",
                "ExitWorktree",
                "LoadSkill",
                "InstallSkill",
                "SendMessage",
                "TaskCreate",
                "TaskGet",
                "TaskList",
                "TaskUpdate",
            ),
        ),
    ],
)
def test_tool_profile_preserves_entrypoint_names_and_order(
    profile: ToolProfile,
    expected_names: tuple[str, ...],
) -> None:
    assert tool_names_for_profile(profile) == expected_names


@pytest.mark.asyncio
async def test_agent_runtime_owns_run_registry_and_extension_session_lifecycle() -> (
    None
):
    async def install(api, bindings) -> None:
        assert bindings == "typed-bindings"
        api.register_tool(_OwnedTool())

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.owned",
                    display_name="Owned test tool",
                    source="test",
                    installer=install,
                )
            ]
        )
    )
    created_agents: list[_FakeAgent] = []

    def create_agent(registry):
        agent = _FakeAgent(registry)
        created_agents.append(agent)
        return agent

    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=ToolProfile.PROMPT_LEAD,
            work_dir="/tmp/runtime-test",
            agent_factory=create_agent,
            bindings_factory=lambda _agent, _registry: "typed-bindings",
        ),
        extension_host=host,
    )

    assert runtime.agent is created_agents[0]
    assert runtime.registry.get("Owned") is not None
    assert [diagnostic.status for diagnostic in runtime.diagnostics] == ["activated"]
    assert runtime.steer_active_run("idle steering") is None
    assert runtime.follow_up_active_run("idle follow-up") is None

    run = runtime.start_run("conversation", "emit", approval="approval")
    assert run is runtime.agent.active_run
    assert runtime.agent.started_with == ("conversation", "emit", "approval")
    assert runtime.steer_active_run("change") == ("steering", "change")
    assert runtime.follow_up_active_run("later") == ("follow_up", "later")
    assert run.queued == [("steering", "change"), ("follow_up", "later")]
    assert runtime.cancel_active_run() is True
    assert run.cancelled is True

    borrowed_view = ToolView.borrow(runtime.registry)
    runtime.agent.registry = borrowed_view

    await runtime.aclose()
    assert run.waited is True
    assert borrowed_view.state == "closed"
    assert runtime.registry.list_contributions() == ()
    assert runtime.state == "closed"

    await runtime.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        runtime.start_run("conversation", "emit")
    with pytest.raises(RuntimeError, match="closed"):
        runtime.steer_active_run("closed")
    with pytest.raises(RuntimeError, match="closed"):
        runtime.follow_up_active_run("closed")
    with pytest.raises(RuntimeError, match="closed"):
        runtime.cancel_active_run()


@pytest.mark.asyncio
async def test_agent_runtimes_isolate_tools_state_and_close_ownership() -> None:
    def install(api, bindings) -> None:
        api.register_tool(_OwnedTool())

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.isolated",
                    display_name="Isolated test tool",
                    source="test",
                    installer=install,
                )
            ]
        )
    )

    async def open_runtime(runtime_id: str) -> AgentRuntime:
        return await AgentRuntime.open(
            AgentRuntimeRequest(
                profile=ToolProfile.PROMPT_LEAD,
                work_dir="/tmp/runtime-test",
                runtime_id=runtime_id,
                agent_factory=_FakeAgent,
                bindings_factory=lambda _agent, _registry: object(),
            ),
            extension_host=host,
        )

    runtime_a = await open_runtime("runtime-a")
    runtime_b = await open_runtime("runtime-b")

    assert runtime_a.registry is not runtime_b.registry
    assert runtime_a.registry.get("Owned") is not runtime_b.registry.get("Owned")
    runtime_a.registry.disable("Owned")
    runtime_a.registry.mark_discovered("Owned")
    assert runtime_a.registry.is_enabled("Owned") is False
    assert runtime_b.registry.is_enabled("Owned") is True
    assert runtime_a.registry.is_discovered("Owned") is True
    assert runtime_b.registry.is_discovered("Owned") is False

    await runtime_a.aclose()

    assert runtime_a.registry.list_contributions() == ()
    assert runtime_b.registry.get("Owned") is not None
    assert runtime_b.state == "active"

    await runtime_b.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", list(ToolProfile))
async def test_builtin_manifest_creates_owned_tools_in_profile_order(
    tmp_path,
    profile: ToolProfile,
) -> None:
    worktree_manager = WorktreeManager(repo_root=str(tmp_path))
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(str(tmp_path))
    skill_loader = SkillLoader(str(tmp_path))
    skill_loader.load_all()
    team_manager = TeamManager(
        worktree_manager=worktree_manager,
        trace_manager=trace_manager,
    )

    def create_agent(registry):
        return _FakeAgent(registry)

    def create_bindings(agent, registry):
        return BuiltinRuntimeBindings(
            agent=agent,
            registry=registry,
            protocol="anthropic",
            agent_loader=agent_loader,
            task_manager=task_manager,
            trace_manager=trace_manager,
            worktree_manager=worktree_manager,
            team_manager=team_manager,
            skill_loader=skill_loader,
        )

    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=profile,
            work_dir=str(tmp_path),
            runtime_id="profile-runtime",
            agent_factory=create_agent,
            bindings_factory=create_bindings,
        ),
        extension_host=create_builtin_extension_host(),
    )

    expected_names = tool_names_for_profile(profile)
    assert tuple(tool.name for tool in runtime.registry.list_tools()) == expected_names
    assert (
        tuple(schema["name"] for schema in runtime.registry.get_all_schemas())
        == expected_names
    )
    assert {
        contribution.owner.extension_id
        for contribution in runtime.registry.list_contributions()
    } == {"koko_pi_agent.builtin-tools"}
    assert {
        contribution.owner.runtime_id
        for contribution in runtime.registry.list_contributions()
    } == {"profile-runtime"}

    await runtime.aclose()
    assert runtime.registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_builtin_profile_missing_required_binding_rolls_back(
    tmp_path,
) -> None:
    worktree_manager = WorktreeManager(repo_root=str(tmp_path))
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(str(tmp_path))
    team_manager = TeamManager(
        worktree_manager=worktree_manager,
        trace_manager=trace_manager,
    )
    created_agents = []

    def create_agent(registry):
        agent = _FakeAgent(registry)
        created_agents.append(agent)
        return agent

    with pytest.raises(ExtensionStartupError, match="skill_loader"):
        await AgentRuntime.open(
            AgentRuntimeRequest(
                profile=ToolProfile.REMOTE_LEAD,
                work_dir=str(tmp_path),
                agent_factory=create_agent,
                bindings_factory=lambda agent, registry: BuiltinRuntimeBindings(
                    agent=agent,
                    registry=registry,
                    protocol="anthropic",
                    agent_loader=agent_loader,
                    task_manager=task_manager,
                    trace_manager=trace_manager,
                    worktree_manager=worktree_manager,
                    team_manager=team_manager,
                ),
            ),
            extension_host=create_builtin_extension_host(),
        )

    assert created_agents[0].registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_prompt_entrypoint_runs_inside_owned_runtime_and_closes_it(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    import koko_pi_agent.client
    from koko_pi_agent.__main__ import _run_prompt

    opened: list[AgentRuntime] = []
    original_open = AgentRuntime.open.__func__

    async def recording_open(cls, request, *, extension_host):
        runtime = await original_open(
            cls,
            request,
            extension_host=extension_host,
        )
        opened.append(runtime)
        return runtime

    async def skip_context_resolution(provider):
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        koko_pi_agent.client, "create_client", lambda provider: _PromptClient()
    )
    monkeypatch.setattr(
        koko_pi_agent.client, "resolve_context_window", skip_context_resolution
    )
    monkeypatch.setattr(AgentRuntime, "open", classmethod(recording_open))
    config = AppConfig(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ],
        enable_fork=False,
    )

    await _run_prompt(
        config,
        PermissionMode.DEFAULT,
        hook_engine=None,
        prompt="hello",
    )

    assert capsys.readouterr().out == "prompt-ok"
    assert len(opened) == 1
    assert opened[0].state == "closed"
    assert opened[0].registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_agent_runtime_reports_unowned_registry_leaks_on_close() -> None:
    host = ExtensionHost(ExtensionCatalog([]))
    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=ToolProfile.PROMPT_LEAD,
            work_dir="/tmp/runtime-test",
            agent_factory=_FakeAgent,
            bindings_factory=lambda _agent, _registry: object(),
        ),
        extension_host=host,
    )
    runtime.registry.register(_OwnedTool())

    await runtime.aclose()

    assert runtime.registry.get("Owned") is not None
    leaked = [item for item in runtime.diagnostics if item.status == "leaked"]
    assert len(leaked) == 1
    assert leaked[0].extension_id == "legacy"
    assert leaked[0].source == "legacy"
    assert "Owned" in leaked[0].error


@pytest.mark.asyncio
async def test_prompt_entrypoint_closes_runtime_when_agent_run_raises(
    tmp_path,
    monkeypatch,
) -> None:
    import koko_pi_agent.client
    from koko_pi_agent.__main__ import _run_prompt

    opened: list[AgentRuntime] = []
    original_open = AgentRuntime.open.__func__

    async def recording_open(cls, request, *, extension_host):
        runtime = await original_open(
            cls,
            request,
            extension_host=extension_host,
        )

        async def failing_run(_conversation):
            raise RuntimeError("prompt run failed")
            yield  # pragma: no cover

        runtime.agent.run = failing_run
        opened.append(runtime)
        return runtime

    async def skip_context_resolution(_provider):
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(koko_pi_agent.client, "create_client", lambda _provider: object())
    monkeypatch.setattr(
        koko_pi_agent.client,
        "resolve_context_window",
        skip_context_resolution,
    )
    monkeypatch.setattr(AgentRuntime, "open", classmethod(recording_open))
    config = AppConfig(
        providers=[
            ProviderConfig(
                name="test",
                protocol="anthropic",
                base_url="http://unused",
                model="test-model",
            )
        ],
        enable_fork=False,
    )

    with pytest.raises(RuntimeError, match="prompt run failed"):
        await _run_prompt(
            config,
            PermissionMode.DEFAULT,
            hook_engine=None,
            prompt="hello",
        )

    assert opened[0].state == "closed"
    assert opened[0].registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_runtime_diagnostics_are_live_not_an_open_time_snapshot() -> None:
    async def explode() -> None:
        raise ValueError("background task exploded")

    def install(api, _bindings) -> None:
        api.register_tool(_OwnedTool())
        api.start_task("exploding", explode())

    host = ExtensionHost(
        ExtensionCatalog(
            [
                ExtensionDefinition(
                    extension_id="test.live-diagnostics",
                    display_name="Live diagnostics",
                    source="test",
                    installer=install,
                )
            ]
        )
    )

    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=ToolProfile.PROMPT_LEAD,
            work_dir="/tmp/runtime-test",
            agent_factory=_FakeAgent,
            bindings_factory=lambda _agent, _registry: "typed-bindings",
        ),
        extension_host=host,
    )

    assert [item.status for item in runtime.diagnostics] == ["activated"]

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # open 时的快照式实现看不到这条：它在 Session 激活之后才产生
    live = [item for item in runtime.diagnostics if item.status == "task_failed"]
    assert len(live) == 1
    assert live[0].name == "exploding"
    assert runtime.state == "active"

    await runtime.aclose()
    assert runtime.state == "closed"


def _resource_bindings_factory(tmp_path, **extra):
    """完整 manager 集合：两个 profile 的内置 Tool 都需要它们才能激活。"""

    worktree_manager = WorktreeManager(repo_root=str(tmp_path))
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(str(tmp_path))
    skill_loader = SkillLoader(str(tmp_path))
    skill_loader.load_all()
    team_manager = TeamManager(
        worktree_manager=worktree_manager,
        trace_manager=trace_manager,
    )

    def create_bindings(agent, registry):
        return BuiltinRuntimeBindings(
            agent=agent,
            registry=registry,
            protocol="anthropic",
            agent_loader=agent_loader,
            task_manager=task_manager,
            trace_manager=trace_manager,
            worktree_manager=worktree_manager,
            team_manager=team_manager,
            skill_loader=skill_loader,
            **extra,
        )

    return create_bindings


@pytest.mark.asyncio
async def test_runtime_resources_definition_activates_as_noop_without_bindings(
    tmp_path,
) -> None:
    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=RuntimeProfile.PROMPT_LEAD,
            work_dir=str(tmp_path),
            agent_factory=_FakeAgent,
            bindings_factory=_resource_bindings_factory(tmp_path),
        ),
        extension_host=create_builtin_extension_host(),
    )

    activated = [
        item.extension_id for item in runtime.diagnostics if item.status == "activated"
    ]
    assert activated == [
        "koko_pi_agent.builtin-tools",
        "koko_pi_agent.runtime-resources",
    ]
    # no-op：没有 mcp_manager / stale_cleanup_factory 就不该贡献任何东西
    assert {
        contribution.owner.extension_id
        for contribution in runtime.registry.list_contributions()
    } == {"koko_pi_agent.builtin-tools"}

    await runtime.aclose()
    assert runtime.state == "closed"
    assert runtime.registry.list_contributions() == ()


@pytest.mark.asyncio
async def test_runtime_resources_owns_mcp_shutdown_and_stale_cleanup(tmp_path) -> None:
    events: list[str] = []
    started = asyncio.Event()

    class _FakeMCPManager:
        async def shutdown(self) -> None:
            events.append("mcp-shutdown")

    async def stale_cleanup() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("stale-cancelled")
            raise

    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=RuntimeProfile.TEAMMATE_WORKER,
            work_dir=str(tmp_path),
            agent_factory=_FakeAgent,
            bindings_factory=_resource_bindings_factory(
                tmp_path,
                mcp_manager=_FakeMCPManager(),
                stale_cleanup_factory=stale_cleanup,
            ),
        ),
        extension_host=create_builtin_extension_host(),
    )

    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert events == []

    await runtime.aclose()

    # 后台任务先被取消并等待，之后才关闭连接管理器
    assert events == ["stale-cancelled", "mcp-shutdown"]
    assert runtime.state == "closed"
