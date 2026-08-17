# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""Agent Team（智能体团队）系统的测试（第 14 章）。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koko_pi_agent.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from koko_pi_agent.teams.shared_task import SharedTask, SharedTaskStore
from koko_pi_agent.teams.mailbox import Mailbox, MailboxMessage, create_message
from koko_pi_agent.teams.registry import AgentNameRegistry
from koko_pi_agent.teams.backend_detect import (
    BackendDetectionError,
    detect_backend,
    detect_backend_from_env,
    detect_pane_backend,
)
from koko_pi_agent.teams.coordinator import (
    get_coordinator_system_prompt,
    get_coordinator_user_context,
)
from koko_pi_agent.agents.tool_filter import (
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
    TEAMMATE_COORDINATION_TOOLS,
    build_teammate_tools,
    apply_coordinator_filter,
)
from koko_pi_agent.tools import ToolRegistry
from koko_pi_agent.tools.base import Tool, ToolResult

# =====================================================================
# 辅助工具
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

@pytest.fixture(autouse=True)
def _reset_registry():
    AgentNameRegistry.reset()
    yield
    AgentNameRegistry.reset()

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)

# =====================================================================
# 1. AgentTeam / TeammateInfo
# =====================================================================

class TestModels:
    def test_teammate_info_roundtrip(self):
        info = TeammateInfo(
            name="alice",
            agent_id="abc123",
            agent_type="worker",
            model="sonnet",
            worktree_path="/tmp/wt",
            backend_type="tmux",
            is_active=True,
        )
        d = info.to_dict()
        restored = TeammateInfo.from_dict(d)
        assert restored.name == "alice"
        assert restored.agent_id == "abc123"
        assert restored.is_active is True

    def test_agent_team_save_load(self, tmp_dir):
        config_path = str(Path(tmp_dir) / "team" / "config.json")
        team = AgentTeam(
            name="test-team",
            lead_agent_id="lead-001",
            config_path=config_path,
            description="Test team",
        )
        team.add_member(TeammateInfo(
            name="alice", agent_id="a1", agent_type="worker",
            model="sonnet", worktree_path="/tmp/wt1", backend_type="tmux",
        ))
        team.save()

        loaded = AgentTeam.load(config_path)
        assert loaded.name == "test-team"
        assert loaded.lead_agent_id == "lead-001"
        assert len(loaded.members) == 1
        assert loaded.members[0].name == "alice"

    def test_get_member(self):
        team = AgentTeam(name="t", lead_agent_id="l")
        team.add_member(TeammateInfo(
            name="bob", agent_id="b1", agent_type="w",
            model="", worktree_path="", backend_type="in-process",
        ))
        assert team.get_member("bob") is not None
        assert team.get_member("b1") is not None
        assert team.get_member("nonexistent") is None

    def test_remove_member(self):
        team = AgentTeam(name="t", lead_agent_id="l")
        team.add_member(TeammateInfo(
            name="bob", agent_id="b1", agent_type="w",
            model="", worktree_path="", backend_type="in-process",
        ))
        assert team.remove_member("bob") is True
        assert len(team.members) == 0
        assert team.remove_member("bob") is False

    def test_set_member_active(self):
        team = AgentTeam(name="t", lead_agent_id="l")
        team.add_member(TeammateInfo(
            name="alice", agent_id="a1", agent_type="w",
            model="", worktree_path="", backend_type="in-process",
            is_active=True,
        ))
        team.set_member_active("alice", False)
        assert team.members[0].is_active is False
        assert team.all_idle() is True

    def test_all_idle(self):
        team = AgentTeam(name="t", lead_agent_id="l")
        team.add_member(TeammateInfo(
            name="alice", agent_id="a1", agent_type="w",
            model="", worktree_path="", backend_type="in-process",
            is_active=False,
        ))
        team.add_member(TeammateInfo(
            name="bob", agent_id="b1", agent_type="w",
            model="", worktree_path="", backend_type="in-process",
            is_active=True,
        ))
        assert team.all_idle() is False

    def test_unique_team_name(self, tmp_dir):
        with patch("koko_pi_agent.teams.models.Path.home", return_value=Path(tmp_dir)):
            name1 = unique_team_name("my-team")
            assert name1 == "my-team"
            (Path(tmp_dir) / ".koko" / "teams" / "my-team").mkdir(parents=True)
            name2 = unique_team_name("my-team")
            assert name2 == "my-team-2"

# =====================================================================
# 2. SharedTaskStore
# =====================================================================

class TestSharedTaskStore:
    def test_create_and_get(self, tmp_dir):
        store = SharedTaskStore(Path(tmp_dir) / "tasks.json")
        store.init_empty()
        task = store.create(title="Do something", description="Details", assignee="alice")
        assert task.id == "1"
        assert task.title == "Do something"

        fetched = store.get("1")
        assert fetched is not None
        assert fetched.assignee == "alice"

    def test_auto_increment_id(self, tmp_dir):
        store = SharedTaskStore(Path(tmp_dir) / "tasks.json")
        store.init_empty()
        t1 = store.create(title="First")
        t2 = store.create(title="Second")
        assert t1.id == "1"
        assert t2.id == "2"

    def test_list_with_filters(self, tmp_dir):
        store = SharedTaskStore(Path(tmp_dir) / "tasks.json")
        store.init_empty()
        store.create(title="A", assignee="alice")
        t2 = store.create(title="B", assignee="bob")
        store.update(t2.id, status="in_progress")

        all_tasks = store.list_tasks()
        assert len(all_tasks) == 2

        pending = store.list_tasks(status="pending")
        assert len(pending) == 1
        assert pending[0].title == "A"

        bobs = store.list_tasks(assignee="bob")
        assert len(bobs) == 1

    def test_update_with_dependencies(self, tmp_dir):
        store = SharedTaskStore(Path(tmp_dir) / "tasks.json")
        store.init_empty()
        store.create(title="Task A")
        store.create(title="Task B")

        updated = store.update("2", add_blocked_by=["1"])
        assert updated is not None
        assert "1" in updated.blocked_by

        updated = store.update("1", add_blocks=["2"])
        assert "2" in updated.blocks

    def test_update_nonexistent_returns_none(self, tmp_dir):
        store = SharedTaskStore(Path(tmp_dir) / "tasks.json")
        store.init_empty()
        assert store.update("999") is None

    def test_persistence(self, tmp_dir):
        path = Path(tmp_dir) / "tasks.json"
        store1 = SharedTaskStore(path)
        store1.init_empty()
        store1.create(title="Persisted task")

        store2 = SharedTaskStore(path)
        tasks = store2.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Persisted task"

# =====================================================================
# 3. Mailbox
# =====================================================================

class TestMailbox:
    def test_write_and_consume(self, tmp_dir):
        mailbox = Mailbox(tmp_dir)
        msg = create_message("alice", "Hello bob")
        mailbox.write("bob-agent-id", msg)

        messages = mailbox.consume("bob-agent-id")
        assert len(messages) == 1
        assert messages[0].text == "Hello bob"
        assert messages[0].from_agent == "alice"

        # 已被消费 —— 此时应该为空
        messages2 = mailbox.consume("bob-agent-id")
        assert len(messages2) == 0

    def test_read_without_consume(self, tmp_dir):
        mailbox = Mailbox(tmp_dir)
        msg = create_message("alice", "Peek")
        mailbox.write("bob-id", msg)

        messages = mailbox.read("bob-id")
        assert len(messages) == 1

        # 仍然存在
        messages2 = mailbox.read("bob-id")
        assert len(messages2) == 1

    def test_broadcast(self, tmp_dir):
        mailbox = Mailbox(tmp_dir)
        msg = create_message("alice", "Team update")
        mailbox.broadcast(["bob-id", "charlie-id", "alice-id"], msg, exclude="alice-id")

        bob_msgs = mailbox.consume("bob-id")
        charlie_msgs = mailbox.consume("charlie-id")
        alice_msgs = mailbox.consume("alice-id")

        assert len(bob_msgs) == 1
        assert len(charlie_msgs) == 1
        assert len(alice_msgs) == 0

    def test_cleanup(self, tmp_dir):
        mailbox = Mailbox(tmp_dir)
        msg = create_message("a", "test")
        mailbox.write("agent-1", msg)
        mailbox.cleanup("agent-1")
        assert len(mailbox.read("agent-1")) == 0

    def test_empty_mailbox(self, tmp_dir):
        mailbox = Mailbox(tmp_dir)
        assert mailbox.consume("nonexistent") == []
        assert mailbox.read("nonexistent") == []

    def test_concurrent_writes_keep_every_message(self, tmp_dir):
        """并发写同一个收件箱时不能丢消息，写失败也必须抛出来而不是静默吞掉。"""
        import threading

        mailbox = Mailbox(tmp_dir)
        n = 20
        errors: list[Exception] = []

        def send(i: int) -> None:
            try:
                mailbox.write("dest", create_message("sender", f"msg-{i}"))
            except Exception as e:  # noqa: BLE001 — 收集起来在主线程断言
                errors.append(e)

        threads = [threading.Thread(target=send, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(mailbox.read("dest")) == n

# =====================================================================
# 4. AgentNameRegistry
# =====================================================================

class TestAgentNameRegistry:

    def test_register_and_resolve(self):
        reg = AgentNameRegistry.instance()
        reg.register("alice", "agent-abc")
        assert reg.resolve("alice") == "agent-abc"
        assert reg.resolve("agent-abc") == "agent-abc"  # 直接按 ID 查找
        assert reg.resolve("nonexistent") is None

    def test_unregister(self):
        reg = AgentNameRegistry.instance()
        reg.register("bob", "agent-xyz")
        reg.unregister("bob")
        assert reg.resolve("bob") is None

    def test_singleton(self):
        r1 = AgentNameRegistry.instance()
        r2 = AgentNameRegistry.instance()
        assert r1 is r2

# =====================================================================
# 5. Backend Detection（后端探测）
# =====================================================================

class TestBackendDetect:
    def _clear_env(self) -> dict[str, str]:
        # 清掉 tmux / iTerm2 相关环境变量，构造“不在任何会话里”的干净环境
        env = {k: v for k, v in os.environ.items()}
        env.pop("TMUX", None)
        env.pop("ITERM_SESSION_ID", None)
        return env

    def test_in_process_mode(self):
        # 显式要求 in-process 时恒回退进程内
        result = detect_backend(teammate_mode="in-process")
        assert result == BackendType.IN_PROCESS

    def test_non_interactive(self):
        # 非交互（-p）模式恒回退进程内
        result = detect_backend(is_interactive=False)
        assert result == BackendType.IN_PROCESS

    def test_from_env_tmux(self):
        env = self._clear_env()
        env["TMUX"] = "/tmp/tmux-1234/default,12345,0"
        with patch.dict(os.environ, env, clear=True):
            assert detect_backend_from_env() == BackendType.TMUX

    def test_from_env_iterm(self):
        env = self._clear_env()
        env["ITERM_SESSION_ID"] = "w0t0p0:ABC-123"
        with patch.dict(os.environ, env, clear=True):
            assert detect_backend_from_env() == BackendType.ITERM2

    def test_from_env_none_is_in_process(self):
        env = self._clear_env()
        with patch.dict(os.environ, env, clear=True):
            assert detect_backend_from_env() == BackendType.IN_PROCESS

    def test_tmux_precedence_over_iterm(self):
        # 同时存在时 tmux 优先
        env = self._clear_env()
        env["TMUX"] = "/tmp/tmux-1234/default,12345,0"
        env["ITERM_SESSION_ID"] = "w0t0p0:ABC-123"
        with patch.dict(os.environ, env, clear=True):
            assert detect_backend_from_env() == BackendType.TMUX

    def test_detect_backend_windows_always_in_process(self):
        # Windows 护栏：即便环境变量指示 tmux，也一律进程内
        env = self._clear_env()
        env["TMUX"] = "/tmp/tmux-1234/default,12345,0"
        with patch.dict(os.environ, env, clear=True):
            with patch("koko_pi_agent.teams.backend_detect.sys.platform", "win32"):
                assert detect_backend() == BackendType.IN_PROCESS

    def test_detect_backend_posix_tmux(self):
        # 非 Windows + 身处 tmux 会话 → tmux 后端
        env = self._clear_env()
        env["TMUX"] = "/tmp/tmux-1234/default,12345,0"
        with patch.dict(os.environ, env, clear=True):
            with patch("koko_pi_agent.teams.backend_detect.sys.platform", "linux"):
                assert detect_backend() == BackendType.TMUX

    def test_detect_backend_posix_no_session(self):
        # 非 Windows 但不在任何会话里 → 进程内
        env = self._clear_env()
        with patch.dict(os.environ, env, clear=True):
            with patch("koko_pi_agent.teams.backend_detect.sys.platform", "linux"):
                assert detect_backend() == BackendType.IN_PROCESS

    def test_pane_backend_posix_iterm(self):
        # detect_pane_backend 只在已身处会话时启用窗格
        env = self._clear_env()
        env["ITERM_SESSION_ID"] = "w0t0p0:ABC-123"
        with patch.dict(os.environ, env, clear=True):
            with patch("koko_pi_agent.teams.backend_detect.sys.platform", "darwin"):
                assert detect_pane_backend() == BackendType.ITERM2

    def test_pane_backend_no_session_falls_back(self):
        # 没有会话环境变量时静默回退进程内，而非抛异常
        env = self._clear_env()
        with patch.dict(os.environ, env, clear=True):
            with patch("koko_pi_agent.teams.backend_detect.sys.platform", "linux"):
                assert detect_pane_backend() == BackendType.IN_PROCESS

# =====================================================================
# 6. Tool Filtering（工具过滤）
# =====================================================================

class TestToolFilter:
    def test_teammate_coordination_tools_in_allowed(self):
        for tool_name in TEAMMATE_COORDINATION_TOOLS:
            assert tool_name in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS

    def test_coordinator_mode_tools(self):
        # 调度必需的工具
        assert "Agent" in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "SendMessage" in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "TaskStop" in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "SyntheticOutput" in COORDINATOR_MODE_ALLOWED_TOOLS
        # 看代码和改代码都该派给队员
        assert "ReadFile" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "Bash" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "Glob" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "Grep" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "WriteFile" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "EditFile" not in COORDINATOR_MODE_ALLOWED_TOOLS
        # 任务表是队员之间协调用的，Lead 靠 task-notification 掌握进度
        assert "TaskCreate" not in COORDINATOR_MODE_ALLOWED_TOOLS
        assert "TaskList" not in COORDINATOR_MODE_ALLOWED_TOOLS

    def test_coordinator_keeps_team_delete_to_avoid_lock_in(self):
        # TeamDelete 是解除 coordinator 模式的唯一入口，
        # 挡掉它 Lead 建完 Team 就再也退不出来
        assert "TeamDelete" in COORDINATOR_MODE_ALLOWED_TOOLS

    def test_apply_coordinator_filter(self):
        reg = make_registry(
            "Agent", "ReadFile", "WriteFile", "Bash", "SendMessage",
            "TaskStop", "SyntheticOutput", "TeamCreate", "TeamDelete",
        )
        filtered = apply_coordinator_filter(reg)
        names = {t.name for t in filtered.list_tools()}
        assert "Agent" in names
        assert "SendMessage" in names
        assert "SyntheticOutput" in names
        assert "TaskStop" in names
        assert "TeamDelete" in names
        assert "ReadFile" not in names
        assert "Bash" not in names
        assert "WriteFile" not in names

    def test_apply_coordinator_filter_drops_mcp_tools(self):
        # MCP 工具的返回值同样可能几千 token，要用就派队员去用
        reg = make_registry("Agent", "mcp__github__create_issue")
        names = {t.name for t in apply_coordinator_filter(reg).list_tools()}
        assert "Agent" in names
        assert "mcp__github__create_issue" not in names

# =====================================================================
# 7. Coordinator Mode（协调者模式）
# =====================================================================

class TestCoordinatorMode:
    def _agent_with_teams(self, enabled: bool, team_count: int):
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.enable_coordinator_mode = enabled
        agent._team_manager = MagicMock()
        agent._team_manager.list_teams.return_value = ["squad"] * team_count
        # 用真实 property 求值，不走 MagicMock 的自动属性
        from koko_pi_agent.agent import Agent
        return Agent.coordinator_mode.fget(agent)

    def test_disabled_when_flag_off(self):
        assert self._agent_with_teams(False, 1) is False

    def test_enabled_from_the_first_turn(self):
        # 只看配置：开了就从第一轮起生效，不等团队建起来。
        # Agent 工具会在团队不存在时自己建，所以不必留个口子给 TeamCreate
        assert self._agent_with_teams(True, 0) is True
        assert self._agent_with_teams(True, 1) is True

    def test_system_prompt_contains_phases(self):
        prompt = get_coordinator_system_prompt()
        assert "Research" in prompt
        assert "Synthesis" in prompt
        assert "Implementation" in prompt
        assert "Verification" in prompt

    def test_system_prompt_anti_pattern(self):
        prompt = get_coordinator_system_prompt()
        assert "based on your findings" in prompt.lower()
        assert "Anti-pattern" in prompt or "BAD" in prompt

    def test_system_prompt_continue_vs_spawn(self):
        prompt = get_coordinator_system_prompt()
        assert "Continue" in prompt
        assert "Spawn fresh" in prompt

    def test_system_prompt_task_notification(self):
        # 指引描述的回传格式必须和 drain_lead_notifications 真正投递的一致，
        # 否则 Lead 会照着一个不存在的字段去找队员名
        prompt = get_coordinator_system_prompt()
        assert "<team-notification" in prompt
        assert "from=" in prompt
        assert "<task_id>" not in prompt

    def test_system_prompt_uses_real_subagent_type(self):
        # MewCode 的内建类型是 general-purpose / plan / explore，没有 worker，
        # 提示词里写 worker 会让 Lead 调用一个不存在的类型
        prompt = get_coordinator_system_prompt()
        assert 'subagent_type: "worker"' not in prompt
        assert "subagent_type `worker`" not in prompt

    def test_coordinator_user_context(self):
        ctx = get_coordinator_user_context()
        assert "workerToolsContext" in ctx
        assert "Workers" in ctx["workerToolsContext"]

# =====================================================================
# 8. Config Extensions（配置项扩展）
# =====================================================================

class TestConfigExtensions:
    def test_teammate_mode_defaults(self):
        from koko_pi_agent.config import AppConfig
        cfg = AppConfig(providers=[])
        assert cfg.teammate_mode == ""
        assert cfg.enable_coordinator_mode is False

    def test_load_config_with_team_fields(self, tmp_dir):
        from koko_pi_agent.config import load_config
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: anthropic\n"
            "    base_url: http://localhost\n"
            "    model: test-model\n"
            "teammate_mode: 'in-process'\n"
            "enable_coordinator_mode: true\n"
        )
        cfg = load_config(config_path)
        assert cfg.teammate_mode == "in-process"
        assert cfg.enable_coordinator_mode is True

    def test_invalid_teammate_mode(self, tmp_dir):
        from koko_pi_agent.config import ConfigError, load_config
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: anthropic\n"
            "    base_url: http://localhost\n"
            "    model: test-model\n"
            "teammate_mode: 'invalid'\n"
        )
        with pytest.raises(ConfigError):
            load_config(config_path)

# =====================================================================
# 9. Transcript Persistence（会话记录持久化）
# =====================================================================

class TestTranscript:

    def test_save_and_load(self, tmp_dir):
        from koko_pi_agent.conversation import ConversationManager
        from koko_pi_agent.teams.transcript import load_transcript, save_transcript

        conv = ConversationManager()
        conv.add_user_message("Hello agent")
        conv.add_assistant_message("Hello user")

        with patch("koko_pi_agent.teams.models.Path.home", return_value=Path(tmp_dir)):
            save_transcript("test-team", "agent-001", conv)
            restored = load_transcript("test-team", "agent-001")

        assert restored is not None
        assert len(restored.history) == 2
        assert restored.history[0].role == "user"
        assert restored.history[0].content == "Hello agent"
        assert restored.history[1].role == "assistant"

    def test_load_nonexistent(self, tmp_dir):
        from koko_pi_agent.teams.transcript import load_transcript
        with patch("koko_pi_agent.teams.models.Path.home", return_value=Path(tmp_dir)):
            result = load_transcript("no-team", "no-agent")
        assert result is None

# =====================================================================
# 10. Agent build_system_prompt 集成测试
# =====================================================================

class TestAgentCoordinatorIntegration:
    def test_normal_prompt(self):
        from koko_pi_agent.prompts import build_system_prompt, IDENTITY_SECTION
        prompt = build_system_prompt()
        # 验证 identity section 内容包含在 prompt 中
        assert "MewCode" in prompt
        assert IDENTITY_SECTION.content[:30] in prompt

    def test_coordinator_guidance_is_a_reminder_not_a_replacement(self):
        # 调度指引每轮以 system-reminder 注入，系统提示词本身不受影响：
        # Lead 进了 coordinator 也仍然需要身份、环境、项目指令这些基础段落
        from koko_pi_agent.prompts import build_system_prompt, IDENTITY_SECTION
        from koko_pi_agent.teams.coordinator import get_coordinator_system_prompt

        prompt = build_system_prompt()
        assert IDENTITY_SECTION.content[:30] in prompt
        assert "coordinator" not in prompt.lower()

        reminder = get_coordinator_system_prompt()
        assert "coordinator" in reminder.lower()

    def test_coordinator_reminder_lists_only_allowed_tools(self):
        from koko_pi_agent.agents.tool_filter import COORDINATOR_MODE_ALLOWED_TOOLS
        from koko_pi_agent.teams.coordinator import get_coordinator_system_prompt

        reminder = get_coordinator_system_prompt()
        section = reminder[
            reminder.index("## 2. Your Tools") : reminder.index("### Worker Results")
        ]
        for name in COORDINATOR_MODE_ALLOWED_TOOLS:
            assert f"**{name}**" in section, f"{name} 没出现在提示词的工具清单里"
        for name in ["ReadFile", "Bash", "Grep", "TaskCreate", "TeamCreate"]:
            assert f"**{name}**" not in section, f"提示词列了被过滤掉的 {name}"


class TestTaskStopTool:
    """TaskStop 让 Lead 在派错方向时及时止损。"""

    def _mgr_with_member(self, backend="in-process", active=True):
        from unittest.mock import MagicMock
        from koko_pi_agent.teams.manager import TeamManager

        mgr = TeamManager()
        team = mgr.create_team("squad", "lead-1", description="t")
        member = TeammateInfo(
            name="scout", agent_id="a1", agent_type="general-purpose",
            model="", worktree_path="", backend_type=backend, is_active=active,
        )
        team.add_member(member)
        return mgr, team, member

    @pytest.mark.asyncio
    async def test_stops_in_process_teammate(self):
        from koko_pi_agent.tools.task_stop import TaskStopTool, TaskStopParams

        mgr, _, member = self._mgr_with_member()
        handle = MagicMock()
        handle.done = False
        mgr.register_inprocess_handle(member.agent_id, handle)

        res = await TaskStopTool(team_manager=mgr).execute(TaskStopParams(teammate="scout"))
        assert not res.is_error
        handle.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_pane_teammate(self):
        # tmux / iTerm2 的队员是独立进程，不走 in-process 句柄，
        # 只认句柄就会漏掉这一类队员
        from koko_pi_agent.tools.task_stop import TaskStopTool, TaskStopParams

        mgr, _, member = self._mgr_with_member(backend="tmux")
        mgr.register_pane_id(member.agent_id, "%42")
        killed = []
        mgr._kill_pane = lambda pane, backend: killed.append((pane, backend))

        res = await TaskStopTool(team_manager=mgr).execute(TaskStopParams(teammate="scout"))
        assert not res.is_error
        assert killed == [("%42", "tmux")]

    @pytest.mark.asyncio
    async def test_unknown_teammate_is_an_error(self):
        from koko_pi_agent.tools.task_stop import TaskStopTool, TaskStopParams

        mgr, _, _ = self._mgr_with_member()
        res = await TaskStopTool(team_manager=mgr).execute(TaskStopParams(teammate="ghost"))
        assert res.is_error

    @pytest.mark.asyncio
    async def test_idle_teammate_is_not_an_error(self):
        # 已经停下的队员再停一次不该报错，免得模型拿着报错反复重试
        from koko_pi_agent.tools.task_stop import TaskStopTool, TaskStopParams

        mgr, _, _ = self._mgr_with_member()
        res = await TaskStopTool(team_manager=mgr).execute(TaskStopParams(teammate="scout"))
        assert not res.is_error
        assert "nothing to stop" in res.output


class TestCoordinatorReminderShape:
    def test_reminder_matches_real_notification_format(self):
        # 指引描述的回传格式必须和 drain 出来的一致
        from koko_pi_agent.teams.coordinator import get_coordinator_system_prompt

        p = get_coordinator_system_prompt()
        assert "<team-notification" in p and "from=" in p
        assert "<task_id>" not in p

    def test_reminder_goes_sparse_after_first_turn(self):
        from koko_pi_agent.teams.coordinator import get_coordinator_reminder

        full = get_coordinator_reminder(1)
        second = get_coordinator_reminder(2)
        assert len(second) < len(full)
        for must in ["cannot read files", "TaskStop", "from="]:
            assert must in second
        assert any(get_coordinator_reminder(i) == full for i in range(2, 13))


class TestTeamFileSchema:
    """config.json 的字段格式：键名一律 camelCase。"""

    def test_config_json_uses_camel_case_keys(self, tmp_dir):
        team = AgentTeam(
            name="squad",
            lead_agent_id="lead",
            config_path=str(Path(tmp_dir) / "config.json"),
            description="d",
        )
        team.add_member(TeammateInfo(
            name="alice", agent_id="a1", agent_type="worker", model="m",
            worktree_path="/wt", backend_type="in-process",
            is_active=False, joined_at=123,
        ))
        team.save()

        data = json.loads(Path(team.config_path).read_text(encoding="utf-8"))
        assert set(data) == {"name", "description", "createdAt", "leadAgentId", "members"}
        assert set(data["members"][0]) == {
            "agentId", "name", "agentType", "model",
            "joinedAt", "worktreePath", "backendType", "isActive",
        }
        # config_path 是运行时算出来的，不该写进文件
        assert "config_path" not in data and "configPath" not in data

    def test_round_trip_keeps_fields(self, tmp_dir):
        cfg = str(Path(tmp_dir) / "config.json")
        team = AgentTeam(name="squad", lead_agent_id="lead", config_path=cfg, description="d")
        team.add_member(TeammateInfo(
            name="alice", agent_id="a1", agent_type="worker", model="m",
            worktree_path="/wt", backend_type="in-process",
            is_active=False, joined_at=123,
        ))
        team.save()

        loaded = AgentTeam.load(cfg)
        assert loaded.lead_agent_id == "lead"
        assert loaded.description == "d"
        assert loaded.created_at > 0
        m = loaded.get_member("alice")
        assert m is not None
        assert (m.agent_id, m.agent_type, m.model, m.worktree_path,
                m.backend_type, m.is_active, m.joined_at) == \
               ("a1", "worker", "m", "/wt", "in-process", False, 123)
