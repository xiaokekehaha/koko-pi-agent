# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""SubAgent 系统的测试（第 12 章）。"""

from __future__ import annotations

import asyncio
import textwrap
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koko_pi_agent.agents.parser import AgentDef, AgentParseError, parse_agent_file, parse_frontmatter
from koko_pi_agent.agents.loader import AgentLoader
from koko_pi_agent.agents.tool_filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    resolve_agent_tools,
)
from koko_pi_agent.agents.fork import (
    FORK_BOILERPLATE_TAG,
    ForkError,
    build_forked_messages,
)
from koko_pi_agent.agents.trace import TraceManager, TraceNode
from koko_pi_agent.agents.task_manager import BackgroundTask, TaskManager
from koko_pi_agent.agents.notification import format_task_notification, inject_task_notifications
from koko_pi_agent.conversation import ConversationManager, Message, ToolResultBlock, ToolUseBlock
from koko_pi_agent.tools import ToolRegistry
from koko_pi_agent.tools.base import Tool, ToolResult

# =====================================================================
# 辅助函数
# =====================================================================

class DummyTool(Tool):
    params_model = MagicMock

    def __init__(self, name: str, category: str = "read"):
        self.name = name
        self.description = f"Dummy {name}"
        self.category = category
        self.is_concurrency_safe = True

    def get_schema(self):
        return {"name": self.name, "description": self.description, "input_schema": {}}

    async def execute(self, params):
        return ToolResult(output=f"{self.name} executed")

def make_registry(*tool_names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for name in tool_names:
        reg.register(DummyTool(name))
    return reg

def make_agent_md(
    name: str = "test-agent",
    description: str = "A test agent",
    body: str = "You are a test agent.",
    **extra_fields: str,
) -> str:
    lines = [f"name: {name}", f"description: {description}"]
    for k, v in extra_fields.items():
        lines.append(f"{k}: {v}")
    frontmatter = "\n".join(lines)
    return f"---\n{frontmatter}\n---\n\n{body}"

# =====================================================================
# 1. Agent 定义解析
# =====================================================================

class TestAgentParser:
    def test_parse_valid_agent(self, tmp_path: Path):
        md = make_agent_md(
            name="security-reviewer",
            description="Security review agent",
            model="haiku",
            maxTurns="20",
        )
        f = tmp_path / "security-reviewer.md"
        f.write_text(md)
        agent_def = parse_agent_file(f)
        assert agent_def.agent_type == "security-reviewer"
        assert agent_def.when_to_use == "Security review agent"
        assert agent_def.model == "haiku"
        assert agent_def.max_turns == 20
        assert agent_def.system_prompt == "You are a test agent."

    def test_parse_missing_name(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("---\ndescription: test\n---\nbody")
        with pytest.raises(AgentParseError, match="name"):
            parse_agent_file(f)

    def test_parse_missing_description(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("---\nname: test\n---\nbody")
        with pytest.raises(AgentParseError, match="description"):
            parse_agent_file(f)

    def test_parse_any_model_accepted(self, tmp_path: Path):
        # 不限制 model 白名单，第三方模型名称由宿主 ModelResolver 校验
        f = tmp_path / "any_model.md"
        f.write_text("---\nname: t\ndescription: t\nmodel: gpt-4\n---\nbody")
        agent_def = parse_agent_file(f)
        assert agent_def.model == "gpt-4"

    def test_parse_invalid_permission_mode(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("---\nname: t\ndescription: t\npermissionMode: yolo\n---\nbody")
        with pytest.raises(AgentParseError, match="permissionMode"):
            parse_agent_file(f)

    def test_parse_invalid_max_turns(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("---\nname: t\ndescription: t\nmaxTurns: -5\n---\nbody")
        with pytest.raises(AgentParseError, match="maxTurns"):
            parse_agent_file(f)

    def test_parse_bad_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("---\n: :\n---\nbody")
        with pytest.raises(AgentParseError):
            parse_agent_file(f)

    def test_parse_no_frontmatter(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text("just text no frontmatter")
        with pytest.raises(AgentParseError, match="frontmatter"):
            parse_agent_file(f)

    def test_parse_disallowed_tools(self, tmp_path: Path):
        md = textwrap.dedent("""\
        ---
        name: reader
        description: Read-only agent
        disallowedTools:
          - EditFile
          - WriteFile
          - Bash
        ---
        Read only.
        """)
        f = tmp_path / "reader.md"
        f.write_text(md)
        agent_def = parse_agent_file(f)
        assert agent_def.disallowed_tools == ["EditFile", "WriteFile", "Bash"]

    def test_parse_default_values(self, tmp_path: Path):
        md = make_agent_md()
        f = tmp_path / "default.md"
        f.write_text(md)
        agent_def = parse_agent_file(f)
        assert agent_def.model == "inherit"
        assert agent_def.max_turns == 200  # 未指定时的默认值
        assert agent_def.permission_mode == "default"
        assert agent_def.background is False
        assert agent_def.tools == []
        assert agent_def.disallowed_tools == []

    def test_frontmatter_parse(self):
        raw = "---\nname: x\ndescription: y\n---\nbody text"
        meta, body = parse_frontmatter(raw)
        assert meta == {"name": "x", "description": "y"}
        assert body == "body text"

    def test_valid_permission_modes(self, tmp_path: Path):
        for mode in ("default", "acceptEdits", "bypassPermissions"):
            f = tmp_path / f"{mode}.md"
            f.write_text(f"---\nname: t\ndescription: t\npermissionMode: {mode}\n---\nbody")
            agent_def = parse_agent_file(f)
            assert agent_def.permission_mode == mode

    def test_valid_models(self, tmp_path: Path):
        for model in ("inherit", "haiku", "sonnet", "opus"):
            f = tmp_path / f"{model}.md"
            f.write_text(f"---\nname: t\ndescription: t\nmodel: {model}\n---\nbody")
            agent_def = parse_agent_file(f)
            assert agent_def.model == model

# =====================================================================
# 2. Agent 加载器
# =====================================================================

class TestAgentLoader:
    def test_load_builtins(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path))
        agents = loader.load_all()
        assert "Explore" in agents
        assert "Plan" in agents
        assert "general-purpose" in agents
        assert agents["Explore"].model == "haiku"
        assert agents["Explore"].max_turns == 200  # 未指定时的默认值

    def test_verification_disabled_by_default(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path), enable_verification=False)
        agents = loader.load_all()
        assert "Verification" not in agents

    def test_verification_enabled(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path), enable_verification=True)
        agents = loader.load_all()
        assert "Verification" in agents

    def test_project_overrides_builtin(self, tmp_path: Path):
        agents_dir = tmp_path / ".koko" / "agents"
        agents_dir.mkdir(parents=True)
        custom_md = make_agent_md(
            name="Explore",
            description="Custom Explore",
            body="Custom system prompt.",
        )
        (agents_dir / "explore.md").write_text(custom_md)

        loader = AgentLoader(str(tmp_path))
        agents = loader.load_all()
        assert agents["Explore"].when_to_use == "Custom Explore"
        assert agents["Explore"].source == "project"

    def test_get_returns_agent(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path))
        loader.load_all()
        explore = loader.get("Explore")
        assert explore is not None
        assert explore.agent_type == "Explore"

    def test_get_unknown_returns_none(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path))
        loader.load_all()
        assert loader.get("nonexistent") is None

    def test_list_agents(self, tmp_path: Path):
        loader = AgentLoader(str(tmp_path))
        loader.load_all()
        agent_list = loader.list_agents()
        names = [name for name, _ in agent_list]
        assert "Explore" in names
        assert "Plan" in names
        assert "general-purpose" in names

    def test_hot_reload(self, tmp_path: Path):
        agents_dir = tmp_path / ".koko" / "agents"
        agents_dir.mkdir(parents=True)
        f = agents_dir / "custom.md"
        f.write_text(make_agent_md(name="custom", description="v1"))

        loader = AgentLoader(str(tmp_path))
        loader.load_all()
        assert loader.get("custom").when_to_use == "v1"

        f.write_text(make_agent_md(name="custom", description="v2"))
        assert loader.get("custom").when_to_use == "v2"

    def test_bad_file_skipped(self, tmp_path: Path):
        agents_dir = tmp_path / ".koko" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "bad.md").write_text("no frontmatter")
        (agents_dir / "good.md").write_text(
            make_agent_md(name="good", description="ok")
        )

        loader = AgentLoader(str(tmp_path))
        agents = loader.load_all()
        assert "good" in agents
        assert "bad" not in agents

# =====================================================================
# 3. 工具过滤
# =====================================================================

class TestToolFilter:

    def test_global_disallowed(self):
        reg = make_registry("ReadFile", "Agent", "Bash", "AskUserQuestion")
        definition = AgentDef(
            agent_type="test", when_to_use="test", source="builtin"
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert "Agent" not in names
        assert "AskUserQuestion" not in names
        assert "ReadFile" in names
        assert "Bash" in names

    def test_disallowed_tools_in_definition(self):
        reg = make_registry("ReadFile", "EditFile", "WriteFile", "Bash", "Grep")
        definition = AgentDef(
            agent_type="test",
            when_to_use="test",
            disallowed_tools=["EditFile", "WriteFile", "Bash"],
            source="builtin",
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert names == {"ReadFile", "Grep"}

    def test_tools_whitelist(self):
        reg = make_registry("ReadFile", "EditFile", "WriteFile", "Bash", "Grep")
        definition = AgentDef(
            agent_type="test",
            when_to_use="test",
            tools=["ReadFile", "Grep"],
            source="builtin",
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert names == {"ReadFile", "Grep"}

    def test_background_whitelist(self):
        reg = make_registry("ReadFile", "EditFile", "WriteFile", "Bash", "Grep", "Agent", "SomeOtherTool")
        definition = AgentDef(
            agent_type="test", when_to_use="test", source="builtin"
        )
        filtered = resolve_agent_tools(reg, definition, is_background=True)
        names = {t.name for t in filtered.list_tools()}
        assert "Agent" not in names
        assert "SomeOtherTool" not in names
        for name in names:
            assert name in ASYNC_AGENT_ALLOWED_TOOLS

    def test_combined_whitelist_and_blacklist(self):
        reg = make_registry("ReadFile", "EditFile", "WriteFile", "Bash", "Grep")
        definition = AgentDef(
            agent_type="test",
            when_to_use="test",
            tools=["ReadFile", "EditFile", "Grep"],
            disallowed_tools=["EditFile"],
            source="builtin",
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert names == {"ReadFile", "Grep"}

    def test_custom_agent_extra_restrictions(self):
        reg = make_registry("ReadFile", "EnterPlanMode", "ExitPlanMode")
        definition = AgentDef(
            agent_type="test", when_to_use="test", source="project"
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert "EnterPlanMode" not in names
        assert "ExitPlanMode" not in names
        assert "ReadFile" in names

    def test_builtin_no_custom_restrictions(self):
        # EnterPlanMode 现在已归入 ALL_AGENT_DISALLOWED，所以应当用一个只在
        # CUSTOM 而不在 ALL 中的工具，来验证内置 agent 会跳过 custom 这一层。
        # ALL 会克隆进 CUSTOM，这里只验证内置 agent 仍然能拿到正常的工具。
        reg = make_registry("ReadFile", "Bash", "Grep")
        definition = AgentDef(
            agent_type="test", when_to_use="test", source="builtin"
        )
        filtered = resolve_agent_tools(reg, definition)
        names = {t.name for t in filtered.list_tools()}
        assert "ReadFile" in names
        assert "Bash" in names

# =====================================================================
# 4. Fork 模式
# =====================================================================

class TestForkMode:
    def test_basic_fork(self):
        conv = ConversationManager()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi there!")
        conv.add_user_message("Do something")

        forked = build_forked_messages(conv, "Write tests")
        messages = forked.history
        assert len(messages) == 4  # 3 条原始消息 + 1 条 fork 任务
        assert FORK_BOILERPLATE_TAG in messages[-1].content
        assert "Write tests" in messages[-1].content

    def test_fork_preserves_history(self):
        conv = ConversationManager()
        conv.add_user_message("msg1")
        conv.add_assistant_message("resp1")
        conv.add_user_message("msg2")
        conv.add_assistant_message("resp2")

        forked = build_forked_messages(conv, "task")
        assert forked.history[0].content == "msg1"
        assert forked.history[1].content == "resp1"
        assert forked.history[2].content == "msg2"
        assert forked.history[3].content == "resp2"

    def test_fork_wraps_pending_tool_use(self):
        conv = ConversationManager()
        conv.add_user_message("Hello")
        conv.add_assistant_message(
            "Let me check",
            [ToolUseBlock(tool_use_id="tu1", tool_name="ReadFile", arguments={"file_path": "x"})],
        )

        forked = build_forked_messages(conv, "task")
        # 应当包含：user、assistant+tool_use、占位的 tool_result、fork 任务
        assert len(forked.history) == 4
        placeholder = forked.history[2]
        assert placeholder.role == "user"
        assert len(placeholder.tool_results) == 1
        assert placeholder.tool_results[0].tool_use_id == "tu1"
        assert placeholder.tool_results[0].content == "interrupted"

    def test_no_double_fork(self):
        conv = ConversationManager()
        conv.add_user_message(f"test {FORK_BOILERPLATE_TAG}")
        with pytest.raises(ForkError, match="Cannot fork"):
            build_forked_messages(conv, "task")

    def test_fork_is_deep_copy(self):
        conv = ConversationManager()
        conv.add_user_message("original")

        forked = build_forked_messages(conv, "task")
        forked.add_user_message("extra")
        assert len(conv.history) == 1
        assert len(forked.history) == 3  # 原始消息 + fork 任务 + 额外消息

# =====================================================================
# 5. Trace 管理器
# =====================================================================

class TestTraceManager:
    def test_create_node(self):
        tm = TraceManager()
        node = tm.create("Explore", parent_id="parent1", trace_id="trace1")
        assert node.agent_type == "Explore"
        assert node.parent_id == "parent1"
        assert node.trace_id == "trace1"
        assert node.status == "running"

    def test_auto_trace_id(self):
        tm = TraceManager()
        node = tm.create("test")
        assert node.trace_id is not None
        assert len(node.trace_id) > 0

    def test_update_tokens(self):
        tm = TraceManager()
        node = tm.create("test")
        tm.update(node.agent_id, input_tokens=100, output_tokens=50)
        updated = tm.get(node.agent_id)
        assert updated.input_tokens == 100
        assert updated.output_tokens == 50

    def test_complete(self):
        tm = TraceManager()
        node = tm.create("test")
        tm.complete(node.agent_id, "completed")
        updated = tm.get(node.agent_id)
        assert updated.status == "completed"
        assert updated.end_time is not None

    def test_get_tree(self):
        tm = TraceManager()
        n1 = tm.create("agent1", trace_id="trace-x")
        n2 = tm.create("agent2", parent_id=n1.agent_id, trace_id="trace-x")
        n3 = tm.create("agent3", trace_id="trace-y")

        tree = tm.get_tree("trace-x")
        ids = {n.agent_id for n in tree}
        assert n1.agent_id in ids
        assert n2.agent_id in ids
        assert n3.agent_id not in ids

    def test_get_total_tokens(self):
        tm = TraceManager()
        n1 = tm.create("a1", trace_id="t1")
        n2 = tm.create("a2", trace_id="t1")
        tm.update(n1.agent_id, input_tokens=100, output_tokens=50)
        tm.update(n2.agent_id, input_tokens=200, output_tokens=80)

        total_in, total_out = tm.get_total_tokens("t1")
        assert total_in == 300
        assert total_out == 130

    def test_get_nonexistent(self):
        tm = TraceManager()
        assert tm.get("nope") is None

    def test_update_nonexistent_is_noop(self):
        tm = TraceManager()
        tm.update("nope", input_tokens=100)

    def test_complete_nonexistent_is_noop(self):
        tm = TraceManager()
        tm.complete("nope", "failed")

# =====================================================================
# 6. 任务管理器
# =====================================================================

class TestTaskManager:
    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.total_input_tokens = 100
        agent.total_output_tokens = 50
        agent.run_to_completion = AsyncMock(return_value="task done")
        # 普通（非团队）subagent：team_name 为空，否则 _run_background 会进入
        # 团队空闲循环（每秒一轮、最多 60 次），后台任务永远走不到 finally 的
        # notify_queue.put，poll_completed 便收不到完成通知。
        agent.team_name = ""
        agent._team_manager = None
        return agent

    @pytest.mark.asyncio
    async def test_launch_and_complete(self, mock_agent):
        tm = TaskManager()
        task_id = tm.launch(mock_agent, "do something", name="test-task")
        assert task_id is not None

        bg = tm.get(task_id)
        assert bg is not None
        assert bg.name == "test-task"
        assert bg.status == "running"

        # 等待任务完成
        await asyncio.sleep(0.1)
        bg = tm.get(task_id)
        assert bg.status == "completed"
        assert bg.result == "task done"

    @pytest.mark.asyncio
    async def test_poll_completed(self, mock_agent):
        tm = TaskManager()
        task_id = tm.launch(mock_agent, "do something")
        await asyncio.sleep(0.1)

        completed = tm.poll_completed()
        assert len(completed) == 1
        assert completed[0].id == task_id

        # 第二次轮询返回空
        assert tm.poll_completed() == []

    @pytest.mark.asyncio
    async def test_cancel(self, mock_agent):
        async def long_running(*a, **kw):
            await asyncio.sleep(10)
            return "done"

        mock_agent.run_to_completion = long_running
        tm = TaskManager()
        task_id = tm.launch(mock_agent, "long task")
        await asyncio.sleep(0.1)

        assert tm.cancel(task_id) is True
        await asyncio.sleep(0.2)

        bg = tm.get(task_id)
        assert bg.status == "cancelled"

    @pytest.mark.asyncio
    async def test_failed_task(self):
        agent = MagicMock()
        agent.total_input_tokens = 0
        agent.total_output_tokens = 0
        agent.run_to_completion = AsyncMock(side_effect=RuntimeError("boom"))

        tm = TaskManager()
        task_id = tm.launch(agent, "will fail")
        await asyncio.sleep(0.1)

        bg = tm.get(task_id)
        assert bg.status == "failed"
        assert "boom" in bg.result

    @pytest.mark.asyncio
    async def test_list_tasks(self, mock_agent):
        tm = TaskManager()
        tm.launch(mock_agent, "task1", name="t1")
        tm.launch(mock_agent, "task2", name="t2")
        tasks = tm.list_tasks()
        assert len(tasks) == 2
        names = {t.name for t in tasks}
        assert names == {"t1", "t2"}
        await asyncio.sleep(0.1)  # 让后台任务跑完

    def test_cancel_nonexistent(self):
        tm = TaskManager()
        assert tm.cancel("nope") is False

# =====================================================================
# 7. 通知
# =====================================================================

class TestNotification:
    def test_format_notification(self):
        bg = BackgroundTask(
            id="abc123",
            name="test-agent",
            agent=MagicMock(),
            task="do stuff",
            status="completed",
            result="All done!",
            start_time=100.0,
            end_time=130.0,
        )
        text = format_task_notification(bg)
        assert "<task-notification>" in text
        assert "abc123" in text
        assert "test-agent" in text
        assert "completed" in text
        assert "All done!" in text
        assert "</task-notification>" in text

    def test_truncate_long_result(self):
        bg = BackgroundTask(
            id="x",
            name="long",
            agent=MagicMock(),
            task="t",
            status="completed",
            result="x" * 10000,
            start_time=100.0,
            end_time=105.0,
        )
        text = format_task_notification(bg)
        assert "truncated" in text

    def test_inject_notifications(self):
        conv = ConversationManager()
        bg1 = BackgroundTask(
            id="t1", name="a1", agent=MagicMock(), task="t",
            status="completed", result="r1",
            start_time=100.0, end_time=105.0,
        )
        bg2 = BackgroundTask(
            id="t2", name="a2", agent=MagicMock(), task="t",
            status="failed", result="r2",
            start_time=100.0, end_time=110.0,
        )
        inject_task_notifications(conv, [bg1, bg2])
        assert len(conv.history) == 2
        assert conv.history[0].role == "user"
        assert "<task-notification>" in conv.history[0].content
        assert "t1" in conv.history[0].content
        assert "t2" in conv.history[1].content

# =====================================================================
# 8. 配置
# =====================================================================

class TestConfig:
    def test_enable_fork_default(self, tmp_path: Path):
        from koko_pi_agent.config import load_config
        cfg = tmp_path / "config.yaml"
        cfg.write_text(textwrap.dedent("""\
        providers:
          - name: test
            protocol: anthropic
            base_url: https://api.example.com
            model: claude-3
        """))
        config = load_config(cfg)
        # fork 默认开着，配置里不写就是开
        assert config.enable_fork is True
        assert config.enable_verification_agent is False

    def test_enable_fork_can_be_disabled(self, tmp_path: Path):
        from koko_pi_agent.config import load_config
        cfg = tmp_path / "config.yaml"
        cfg.write_text(textwrap.dedent("""\
        providers:
          - name: test
            protocol: anthropic
            base_url: https://api.example.com
            model: claude-3
        enable_fork: false
        enable_verification_agent: true
        """))
        config = load_config(cfg)
        # 写 false 必须真的关掉，不能被「非零即覆盖」的合并逻辑吃掉
        assert config.enable_fork is False
        assert config.enable_verification_agent is True

# =====================================================================
# 9. 权限模式
# =====================================================================

class TestPermissionMode:
    def test_bypass_mode(self):
        from koko_pi_agent.permissions.modes import PermissionMode, mode_decide
        assert PermissionMode.BYPASS.value == "bypassPermissions"
        assert mode_decide(PermissionMode.BYPASS, "read") == "allow"
        assert mode_decide(PermissionMode.BYPASS, "write") == "allow"
        assert mode_decide(PermissionMode.BYPASS, "command") == "allow"

# =====================================================================
# 10. AgentTool 参数
# =====================================================================

class TestAgentToolParams:
    def test_required_fields(self):
        from koko_pi_agent.tools.agent_tool import AgentToolParams
        params = AgentToolParams(prompt="do this", description="test")
        assert params.prompt == "do this"
        assert params.subagent_type is None
        assert params.run_in_background is False

    def test_optional_fields(self):
        from koko_pi_agent.tools.agent_tool import AgentToolParams
        params = AgentToolParams(
            prompt="do",
            description="test",
            subagent_type="Explore",
            model="haiku",
            run_in_background=True,
            name="my-agent",
            isolation="worktree",
        )
        assert params.subagent_type == "Explore"
        assert params.model == "haiku"
        assert params.run_in_background is True
        assert params.name == "my-agent"
        assert params.isolation == "worktree"

# =====================================================================
# 11. Agent（run_to_completion 基础功能、agent_id、trace_id）
# =====================================================================

class TestAgentExtensions:
    def test_agent_has_id(self):
        from koko_pi_agent.agent import Agent
        client = MagicMock()
        registry = ToolRegistry()
        agent = Agent(client=client, registry=registry, protocol="anthropic")
        assert agent.agent_id is not None
        assert len(agent.agent_id) > 0
        assert agent.parent_id is None
        assert agent.trace_id is None

    def test_agent_catalog(self):
        from koko_pi_agent.agent import Agent
        client = MagicMock()
        registry = ToolRegistry()
        agent = Agent(client=client, registry=registry, protocol="anthropic")
        agent.set_agent_catalog("## Agents\n- Explore")
        assert agent._agent_catalog == "## Agents\n- Explore"
