# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""
SubAgent 系统端到端验证脚本。
不依赖 LLM，直接调用核心组件验证所有 Agent 类型和关键流程。

运行: .venv/bin/python tests/verify_subagent.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mewcode.agents.loader import AgentLoader
from mewcode.agents.tool_filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    resolve_agent_tools,
)
from mewcode.agents.fork import FORK_BOILERPLATE_TAG, ForkError, build_forked_messages
from mewcode.agents.trace import TraceManager
from mewcode.agents.task_manager import TaskManager
from mewcode.agents.notification import format_task_notification, inject_task_notifications
from mewcode.conversation import ConversationManager, ToolUseBlock
from mewcode.tools import ToolRegistry
from mewcode.tools.base import Tool, ToolResult
from mewcode.config import load_config

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
passed = 0
failed = 0

def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {PASS} {name}")
    else:
        failed += 1
        msg = f"  {FAIL} {name}"
        if detail:
            msg += f"  — {detail}"
        print(msg)

# ---------------------------------------------------------------------------
# 用于测试的占位（dummy）工具
# ---------------------------------------------------------------------------
class DummyTool(Tool):
    from pydantic import BaseModel as _BM

    class _Params(_BM):
        pass

    params_model = _Params

    def __init__(self, name: str):
        self.name = name
        self.description = f"Dummy {name}"
        self.category = "read"
        self.is_concurrency_safe = True

    def get_schema(self):
        return {"name": self.name, "description": self.description, "input_schema": {}}

    async def execute(self, params):
        return ToolResult(output=f"{self.name} ok")

def make_registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(DummyTool(n))
    return reg

# ---------------------------------------------------------------------------
# 1. Agent 定义加载
# ---------------------------------------------------------------------------

def verify_loader():
    print("\n== 1. Agent 定义加载 ==")
    work_dir = str(Path(__file__).resolve().parent.parent)

    # 不带 Verification
    loader = AgentLoader(work_dir, enable_verification=False)
    agents = loader.load_all()

    check("内置 Explore 加载", "Explore" in agents)
    check("内置 Plan 加载", "Plan" in agents)
    check("内置 general-purpose 加载", "general-purpose" in agents)
    check("Verification 默认不加载", "Verification" not in agents)

    # 带 Verification
    loader_v = AgentLoader(work_dir, enable_verification=True)
    agents_v = loader_v.load_all()
    check("Verification 开关开启后加载", "Verification" in agents_v)

    # 自定义 Agent
    check(
        "自定义 security-reviewer 加载",
        "security-reviewer" in agents,
        f"实际加载: {list(agents.keys())}",
    )
    check(
        "自定义 code-summarizer 加载",
        "code-summarizer" in agents,
        f"实际加载: {list(agents.keys())}",
    )

    # 自定义 Agent 来源标记
    if "security-reviewer" in agents:
        check(
            "自定义 Agent source=project",
            agents["security-reviewer"].source == "project",
        )

    # 属性验证
    explore = loader.get("Explore")
    check("Explore model=haiku", explore is not None and explore.model == "haiku")
    # maxTurns not capped (defaults to 200)
    check("Explore maxTurns=200", explore is not None and explore.max_turns == 200)
    check(
        "Explore disallowedTools 包含 EditFile",
        explore is not None and "EditFile" in explore.disallowed_tools,
    )

    plan = loader.get("Plan")
    check("Plan maxTurns=15", plan is not None and plan.max_turns == 15)

    sr = loader.get("security-reviewer")
    check("security-reviewer model=haiku", sr is not None and sr.model == "haiku")
    check(
        "security-reviewer permissionMode=bypassPermissions",
        sr is not None and sr.permission_mode == "bypassPermissions",
    )

    check("get 未知类型返回 None", loader.get("nonexistent") is None)

    # list_agents
    agent_list = loader.list_agents()
    names = [n for n, _ in agent_list]
    check("list_agents 包含所有加载的 Agent", len(names) >= 5)

    return loader

# ---------------------------------------------------------------------------
# 2. 工具过滤
# ---------------------------------------------------------------------------
def verify_tool_filter(loader: AgentLoader):
    print("\n== 2. 工具过滤（四层） ==")

    all_tools = [
        "ReadFile", "EditFile", "WriteFile", "Bash", "Grep", "Glob",
        "Agent", "AskUserQuestion", "TaskStop",
        "EnterPlanMode", "ExitPlanMode", "LoadSkill",
    ]
    reg = make_registry(*all_tools)

    # 内置 Explore
    explore = loader.get("Explore")
    filtered = resolve_agent_tools(reg, explore, is_background=False)
    names = {t.name for t in filtered.list_tools()}

    check("L1: Agent 被全局禁止", "Agent" not in names)
    check("L1: AskUserQuestion 被全局禁止", "AskUserQuestion" not in names)
    check("L1: TaskStop 被全局禁止", "TaskStop" not in names)
    check(
        "L4: Explore disallowedTools 生效 (EditFile)",
        "EditFile" not in names,
    )
    check(
        "L4: Explore disallowedTools 生效 (WriteFile)",
        "WriteFile" not in names,
    )
    check("Explore 保留 ReadFile", "ReadFile" in names)
    check("Explore 保留 Grep", "Grep" in names)
    check("Explore 保留 Bash", "Bash" in names)

    # 自定义 Agent (source=project) — 应该触发 L2
    sr = loader.get("security-reviewer")
    filtered_sr = resolve_agent_tools(reg, sr, is_background=False)
    names_sr = {t.name for t in filtered_sr.list_tools()}
    check("L2: 自定义 Agent 额外禁止 EnterPlanMode", "EnterPlanMode" not in names_sr)

    # general-purpose 没有 disallow EnterPlanMode，验证内置不受 L2 限制
    gp_fg = resolve_agent_tools(reg, loader.get("general-purpose"), is_background=False)
    names_gp = {t.name for t in gp_fg.list_tools()}
    check("L2: 内置 Agent 不禁止 EnterPlanMode", "EnterPlanMode" in names_gp)

    # 后台白名单
    gp = loader.get("general-purpose")
    filtered_bg = resolve_agent_tools(reg, gp, is_background=True)
    names_bg = {t.name for t in filtered_bg.list_tools()}
    check("L3: 后台 Agent 不含 Agent 工具", "Agent" not in names_bg)
    for n in names_bg:
        if n not in ASYNC_AGENT_ALLOWED_TOOLS:
            check(f"L3: 后台工具 {n} 不在白名单中", False)
            break
    else:
        check("L3: 后台所有工具都在白名单中", True)

    # 白名单+黑名单组合
    from mewcode.agents.parser import AgentDef
    combo = AgentDef(
        agent_type="combo",
        when_to_use="test",
        tools=["ReadFile", "EditFile", "Grep"],
        disallowed_tools=["EditFile"],
        source="builtin",
    )
    filtered_combo = resolve_agent_tools(reg, combo)
    names_combo = {t.name for t in filtered_combo.list_tools()}
    check("白名单+黑名单组合: 只剩 ReadFile+Grep", names_combo == {"ReadFile", "Grep"})

# ---------------------------------------------------------------------------
# 3. Fork 模式
# ---------------------------------------------------------------------------

def verify_fork():
    print("\n== 3. Fork 模式 ==")

    conv = ConversationManager()
    conv.add_user_message("你好")
    conv.add_assistant_message("你好！有什么可以帮你的？")
    conv.add_user_message("帮我看看 config.py")
    conv.add_assistant_message("好的，我来读取这个文件。")

    forked = build_forked_messages(conv, "顺便写个单元测试")
    check("Fork 保留原始对话", len(forked.history) == 5)  # 4 条原始消息 + 1 条 fork 消息
    check(
        "Fork 末尾注入 boilerplate",
        FORK_BOILERPLATE_TAG in forked.history[-1].content,
    )
    check("Fork 末尾包含任务", "顺便写个单元测试" in forked.history[-1].content)

    # 深拷贝验证
    forked.add_user_message("额外消息")
    check("Fork 是深拷贝，不影响原对话", len(conv.history) == 4)

    # 未完成 tool_use 包装
    conv2 = ConversationManager()
    conv2.add_user_message("test")
    conv2.add_assistant_message(
        "reading",
        [ToolUseBlock(tool_use_id="tu1", tool_name="ReadFile", arguments={})],
    )
    forked2 = build_forked_messages(conv2, "task")
    has_placeholder = any(
        msg.tool_results and msg.tool_results[0].content == "interrupted"
        for msg in forked2.history
    )
    check("未完成 tool_use 被包装为 placeholder", has_placeholder)

    # 禁止再 Fork
    try:
        build_forked_messages(forked, "再 fork 一次")
        check("禁止再 Fork", False, "应该抛出 ForkError")
    except ForkError:
        check("禁止再 Fork", True)

# ---------------------------------------------------------------------------
# 4. Trace 链路追踪
# ---------------------------------------------------------------------------
def verify_trace():
    print("\n== 4. 父子链路追踪 ==")
    tm = TraceManager()

    root = tm.create("main", trace_id="trace-001")
    child1 = tm.create("Explore", parent_id=root.agent_id, trace_id="trace-001")
    child2 = tm.create("Plan", parent_id=root.agent_id, trace_id="trace-001")
    other = tm.create("other", trace_id="trace-002")

    check("创建节点成功", tm.get(root.agent_id) is not None)
    check("parent_id 正确", child1.parent_id == root.agent_id)
    check("trace_id 继承", child1.trace_id == "trace-001")

    tm.update(root.agent_id, input_tokens=1000, output_tokens=500)
    tm.update(child1.agent_id, input_tokens=200, output_tokens=100)
    tm.update(child2.agent_id, input_tokens=300, output_tokens=150)

    tree = tm.get_tree("trace-001")
    check("get_tree 返回同 trace 节点", len(tree) == 3)
    check("get_tree 不含其他 trace", other.agent_id not in {n.agent_id for n in tree})

    total_in, total_out = tm.get_total_tokens("trace-001")
    check("汇总 input_tokens=1500", total_in == 1500)
    check("汇总 output_tokens=750", total_out == 750)

    tm.complete(child1.agent_id, "completed")
    check("complete 设置状态", tm.get(child1.agent_id).status == "completed")
    check("complete 设置 end_time", tm.get(child1.agent_id).end_time is not None)

# ---------------------------------------------------------------------------
# 5. TaskManager 后台任务
# ---------------------------------------------------------------------------
async def verify_task_manager():
    print("\n== 5. TaskManager 后台任务 ==")

    from unittest.mock import MagicMock, AsyncMock

    agent = MagicMock()
    agent.total_input_tokens = 200
    agent.total_output_tokens = 80
    agent.run_to_completion = AsyncMock(return_value="搜索完成，找到 15 个 .py 文件")

    tm = TaskManager()

    # launch
    task_id = tm.launch(agent, "搜索项目结构", name="explore-task")
    check("launch 返回 task_id", task_id is not None and len(task_id) > 0)
    check("任务初始状态 running", tm.get(task_id).status == "running")

    await asyncio.sleep(0.2)

    bg = tm.get(task_id)
    check("任务完成后状态 completed", bg.status == "completed")
    check("任务结果正确", "15 个 .py 文件" in bg.result)
    check("token 统计更新", bg.progress.input_tokens == 200)

    # poll
    completed = tm.poll_completed()
    check("poll_completed 返回已完成任务", len(completed) == 1)
    check("二次 poll 为空", len(tm.poll_completed()) == 0)

    # list
    check("list_tasks 包含任务", len(tm.list_tasks()) == 1)

    # cancel
    slow_agent = MagicMock()
    slow_agent.total_input_tokens = 0
    slow_agent.total_output_tokens = 0

    async def slow_run(*a, **kw):
        await asyncio.sleep(10)
        return "done"

    slow_agent.run_to_completion = slow_run
    slow_id = tm.launch(slow_agent, "慢任务", name="slow")
    await asyncio.sleep(0.1)
    check("cancel 运行中任务", tm.cancel(slow_id) is True)
    await asyncio.sleep(0.2)
    check("cancel 后状态", tm.get(slow_id).status == "cancelled")

    # failed
    bad_agent = MagicMock()
    bad_agent.total_input_tokens = 0
    bad_agent.total_output_tokens = 0
    bad_agent.run_to_completion = AsyncMock(side_effect=RuntimeError("boom"))
    bad_id = tm.launch(bad_agent, "会失败的任务", name="bad")
    await asyncio.sleep(0.2)
    check("异常任务状态 failed", tm.get(bad_id).status == "failed")
    check("异常任务包含错误信息", "boom" in tm.get(bad_id).result)

# ---------------------------------------------------------------------------
# 6. Notification 通知
# ---------------------------------------------------------------------------
def verify_notification():
    print("\n== 6. task-notification 通知 ==")
    from mewcode.agents.task_manager import BackgroundTask

    bg = BackgroundTask(
        id="abc123",
        name="security-reviewer",
        agent=None,
        task="审查 config.py",
        status="completed",
        result="发现 1 个 Critical: 硬编码 API Key",
        start_time=100.0,
        end_time=145.0,
    )

    text = format_task_notification(bg)
    check("通知包含 <task-notification>", "<task-notification>" in text)
    check("通知包含 task ID", "abc123" in text)
    check("通知包含 agent name", "security-reviewer" in text)
    check("通知包含 status", "completed" in text)
    check("通知包含 result", "硬编码 API Key" in text)
    check("通知包含 </task-notification>", "</task-notification>" in text)

    conv = ConversationManager()
    inject_task_notifications(conv, [bg])
    check("注入后消息角色为 user", conv.history[0].role == "user")
    check("注入后内容包含通知", "<task-notification>" in conv.history[0].content)

# ---------------------------------------------------------------------------
# 7. Config 配置
# ---------------------------------------------------------------------------

def verify_config():
    print("\n== 7. 配置扩展 ==")
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if not config_path.exists():
        check("config.yaml 存在", False, str(config_path))
        return

    config = load_config(config_path)
    check("enable_fork 读取成功", isinstance(config.enable_fork, bool))
    check("enable_verification_agent 读取成功", isinstance(config.enable_verification_agent, bool))
    check("enable_fork=True", config.enable_fork is True)
    check("enable_verification_agent=True", config.enable_verification_agent is True)

# ---------------------------------------------------------------------------
# 8. 权限模式
# ---------------------------------------------------------------------------
def verify_permission():
    print("\n== 8. BYPASS 权限模式 ==")
    from mewcode.permissions.modes import PermissionMode, mode_decide

    check("BYPASS 枚举值", PermissionMode.BYPASS.value == "bypassPermissions")
    check("BYPASS read=allow", mode_decide(PermissionMode.BYPASS, "read") == "allow")
    check("BYPASS write=allow", mode_decide(PermissionMode.BYPASS, "write") == "allow")
    check("BYPASS command=allow", mode_decide(PermissionMode.BYPASS, "command") == "allow")

# ---------------------------------------------------------------------------
# 9. Agent 扩展字段
# ---------------------------------------------------------------------------
def verify_agent_fields():
    print("\n== 9. Agent 扩展字段 ==")
    from mewcode.agent import Agent
    from unittest.mock import MagicMock

    agent = Agent(
        client=MagicMock(),
        registry=ToolRegistry(),
        protocol="anthropic",
    )
    check("agent_id 自动生成", agent.agent_id is not None and len(agent.agent_id) == 12)
    check("parent_id 默认 None", agent.parent_id is None)
    check("trace_id 默认 None", agent.trace_id is None)

    agent.set_agent_catalog("## Agents\n- Explore: 搜索")
    check("set_agent_catalog 生效", "Explore" in agent._agent_catalog)

# ---------------------------------------------------------------------------
# 10. AgentTool 参数模型
# ---------------------------------------------------------------------------
def verify_agent_tool():
    print("\n== 10. AgentTool 参数与 schema ==")
    from mewcode.tools.agent_tool import AgentTool, AgentToolParams

    params = AgentToolParams(
        prompt="探索项目结构",
        description="代码探索",
        subagent_type="Explore",
        model="haiku",
        run_in_background=True,
        name="my-explore",
    )
    check("必填参数 prompt", params.prompt == "探索项目结构")
    check("必填参数 description", params.description == "代码探索")
    check("可选 subagent_type", params.subagent_type == "Explore")
    check("可选 model", params.model == "haiku")
    check("可选 run_in_background", params.run_in_background is True)
    check("可选 name", params.name == "my-explore")

    # Schema 验证
    schema = AgentToolParams.model_json_schema()
    required = schema.get("required", [])
    check("prompt 是 required", "prompt" in required)
    check("description 是 required", "description" in required)
    check("subagent_type 不是 required", "subagent_type" not in required)

    # worktree 未实现
    params_wt = AgentToolParams(
        prompt="test", description="test", isolation="worktree"
    )
    check("isolation 参数可设置", params_wt.isolation == "worktree")

# ===========================================================================
# 主流程
# ===========================================================================
async def main():
    global passed, failed

    print("=" * 60)
    print("  SubAgent 系统验证（第 12 章）")
    print("=" * 60)

    loader = verify_loader()
    verify_tool_filter(loader)
    verify_fork()
    verify_trace()
    await verify_task_manager()
    verify_notification()
    verify_config()
    verify_permission()
    verify_agent_fields()
    verify_agent_tool()

    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"  \033[32m全部通过: {passed}/{total}\033[0m")
    else:
        print(f"  \033[31m失败: {failed}/{total}\033[0m")
    print("=" * 60)

    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
