# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from koko_pi_agent.config import ConfigError, load_config
from koko_pi_agent.hooks import HookConfigError, HookEngine, load_hooks
from koko_pi_agent.permissions import PermissionMode


def main() -> None:
    # 队友 worker 模式：由 tmux/iTerm2 窗格用 `-m koko_pi_agent --teammate ...` 拉起。
    # 必须在 argparse 之前拦截，走独立的 worker 分支而不是正常 TUI。
    teammate = _parse_teammate_flags(sys.argv[1:])
    if teammate is not None:
        asyncio.run(_run_teammate(*teammate))
        return

    # 先确保 .koko/ 目录存在，否则下面写 debug.log 会因目录不存在而崩溃
    Path(".koko").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=".koko/debug.log",
        filemode="w",
    )

    parser = argparse.ArgumentParser(prog="koko", description="Koko Pi Agent coding assistant")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in PermissionMode],
        default=None,
        help="Permission mode (overrides config.yaml)",
    )
    parser.add_argument(
        "-p",
        metavar="PROMPT",
        default=None,
        help="Run non-interactively: execute the prompt and print the result to stdout",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "stream-json"],
        default="text",
        help="Output format for -p mode: 'text' (default) prints final text, 'stream-json' emits NDJSON events",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        default=False,
        help="Start in remote mode: WebSocket server on 0.0.0.0:18888 with browser UI",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    mode_str = args.mode if args.mode else config.permission_mode
    permission_mode = PermissionMode(mode_str)

    try:
        hooks = load_hooks(config.raw_hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    hook_engine = HookEngine(hooks) if hooks else None

    if args.p is not None:
        output_format = getattr(args, "output_format", "text")
        asyncio.run(_run_prompt(config, permission_mode, hook_engine, args.p, output_format))
        return

    # Remote 模式：启动 WebSocket 服务器，浏览器访问 http://localhost:18888
    if args.remote:
        from koko_pi_agent.remote import RemoteServer

        server = RemoteServer(
            providers=config.providers,
            mcp_servers=config.mcp_servers,
            hook_engine=hook_engine,
            config=config,
        )
        asyncio.run(server.run())
        return

    from koko_pi_agent.app import KokoApp
    from koko_pi_agent.driver import NoAltScreenDriver

    app = KokoApp(
        providers=config.providers,
        permission_mode=permission_mode,
        mcp_servers=config.mcp_servers,
        hook_engine=hook_engine,
        enable_fork=config.enable_fork,
        enable_verification_agent=config.enable_verification_agent,
        worktree_config=config.worktree,
        teammate_mode=config.teammate_mode,
        enable_coordinator_mode=config.enable_coordinator_mode,
        driver_class=NoAltScreenDriver,
        sandbox_config=config.sandbox,
    )
    app.run()


async def _run_prompt(config, permission_mode, hook_engine, prompt: str, output_format: str = "text") -> None:
    from koko_pi_agent.agent import (
        Agent,
        CompactNotification,
        ErrorEvent,
        LoopComplete,
        PermissionRequest,
        PermissionResponse,
        RetryEvent,
        StreamText,
        ThinkingText,
        ToolResultEvent,
        ToolUseEvent,
        TurnComplete,
        UsageEvent,
    )
    from koko_pi_agent.client import create_client, resolve_context_window
    from koko_pi_agent.conversation import ConversationManager
    from koko_pi_agent.memory.instructions import load_instructions
    from koko_pi_agent.permissions import (
        DangerousCommandDetector,
        PathSandbox,
        PermissionChecker,
        RuleEngine,
    )
    from koko_pi_agent.extensions import (
        BuiltinRuntimeBindings,
        RuntimeProfile,
        create_builtin_extension_host,
    )
    from koko_pi_agent.runtime import AgentRuntime, AgentRuntimeRequest
    from koko_pi_agent.agents.loader import AgentLoader
    from koko_pi_agent.agents.task_manager import TaskManager
    from koko_pi_agent.agents.trace import TraceManager
    from koko_pi_agent.teams.manager import TeamManager
    from koko_pi_agent.worktree import WorktreeManager
    from koko_pi_agent.config import WorktreeConfig

    is_json = output_format == "stream-json"

    def emit_json(obj: dict) -> None:
        """输出一行 NDJSON 到 stdout"""
        print(json.dumps(obj, ensure_ascii=False), flush=True)

    provider = config.providers[0]
    client = create_client(provider)
    # 第 2 层：尽力从 provider 自动拉取模型的 context window（缓存在 provider 上）。
    # 不会抛异常或阻塞启动；失败则退化到映射表。
    await resolve_context_window(provider)
    work_dir = os.getcwd()
    home = Path.home()

    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(
            user_rules_path=home / ".koko" / "permissions.yaml",
            project_rules_path=Path(work_dir) / ".koko" / "permissions.yaml",
            local_rules_path=Path(work_dir) / ".koko" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )

    instructions = load_instructions(work_dir)
    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(work_dir, enable_verification=config.enable_verification_agent)
    agent_loader.load_all()
    team_manager = TeamManager(worktree_manager=wt_manager, trace_manager=trace_manager)

    def create_agent(registry):
        return Agent(
            client=client,
            registry=registry,
            protocol=provider.protocol,
            work_dir=work_dir,
            permission_checker=checker,
            context_window=provider.get_context_window(),
            instructions_content=instructions,
            hook_engine=hook_engine,
        )

    def create_bindings(agent, registry):
        return BuiltinRuntimeBindings(
            agent=agent,
            registry=registry,
            protocol=provider.protocol,
            agent_loader=agent_loader,
            task_manager=task_manager,
            trace_manager=trace_manager,
            provider_config=provider,
            worktree_manager=wt_manager,
            team_manager=team_manager,
            enable_fork=config.enable_fork,
            teammate_mode="in-process",
            is_interactive=False,
            enable_coordinator_mode=config.enable_coordinator_mode,
        )

    runtime = await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=RuntimeProfile.PROMPT_LEAD,
            work_dir=work_dir,
            agent_factory=create_agent,
            bindings_factory=create_bindings,
        ),
        extension_host=create_builtin_extension_host(),
    )
    agent = runtime.agent

    async def run_active_runtime() -> None:
        # coordinator 模式由配置决定，开了就从第一轮起收窄工具集
        if config.enable_coordinator_mode:
            from koko_pi_agent.agents.tool_filter import apply_coordinator_filter

            agent.enable_coordinator_mode = True
            agent.registry = apply_coordinator_filter(agent.registry)

        def drain_notifications() -> list[str]:
            notes: list[str] = []
            for t in task_manager.poll_completed():
                notes.append(
                    f"<task-notification>\n<task_id>{t.id}</task_id>\n"
                    f"<status>{t.status}</status>\n<result>{t.result}</result>\n"
                    f"</task-notification>"
                )
            notes.extend(team_manager.drain_lead_mailbox())
            return notes

        def drain_mailbox_only() -> list[str]:
            return team_manager.drain_lead_mailbox()

        agent.notification_fn = drain_mailbox_only

        # 使用事件驱动的 agent.run()，支持 text 和 stream-json 两种输出格式
        conv = ConversationManager()
        conv.add_user_message(prompt)

        start = time.monotonic()
        text_buf = ""
        total_input = 0
        total_output = 0
        tool_calls: list[dict] = []

        async for event in agent.run(conv):
            if isinstance(event, StreamText):
                text_buf += event.text
                if is_json:
                    emit_json({"type": "assistant", "text": event.text})

            elif isinstance(event, ThinkingText):
                if is_json:
                    emit_json({"type": "thinking", "text": event.text})

            elif isinstance(event, ToolUseEvent):
                tool_calls.append({"name": event.tool_name, "is_error": False})
                if is_json:
                    emit_json({
                        "type": "tool_use",
                        "tool_name": event.tool_name,
                        "tool_id": event.tool_id,
                        "args": event.arguments,
                    })

            elif isinstance(event, ToolResultEvent):
                # 回填最后一个同名 tool_call 的 is_error
                if tool_calls:
                    tool_calls[-1]["is_error"] = event.is_error
                if is_json:
                    emit_json({
                        "type": "tool_result",
                        "tool_name": event.tool_name,
                        "tool_id": event.tool_id,
                        "output": event.output,
                        "is_error": event.is_error,
                        "elapsed": round(event.elapsed, 3),
                    })

            elif isinstance(event, UsageEvent):
                total_input = event.input_tokens
                total_output = event.output_tokens
                if is_json:
                    emit_json({
                        "type": "usage",
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                    })

            elif isinstance(event, TurnComplete):
                if is_json:
                    emit_json({"type": "turn_complete", "turn": event.turn})

            elif isinstance(event, LoopComplete):
                # 最终结果：stream-json 输出 result 行，text 模式直接打印文本
                elapsed_ms = int((time.monotonic() - start) * 1000)
                if is_json:
                    emit_json({
                        "type": "result",
                        "result": text_buf,
                        "duration_ms": elapsed_ms,
                        "num_turns": event.total_turns,
                        "tool_calls": tool_calls,
                        "usage": {
                            "input_tokens": total_input,
                            "output_tokens": total_output,
                        },
                        "stop_reason": "end_turn",
                    })
                else:
                    print(text_buf, end="", flush=True)
                break

            elif isinstance(event, ErrorEvent):
                if is_json:
                    emit_json({"type": "error", "message": event.message})
                else:
                    print(f"Error: {event.message}", file=sys.stderr, flush=True)

            elif isinstance(event, CompactNotification):
                if is_json:
                    emit_json({"type": "compact", "message": event.message})

            elif isinstance(event, RetryEvent):
                if is_json:
                    emit_json({"type": "retry", "reason": event.reason})

            elif isinstance(event, PermissionRequest):
                # -p 非交互模式：自动批准所有权限请求
                event.future.set_result(PermissionResponse.ALLOW)

        # 如果有 team 在运行，轮询等待 teammate 完成
        if not team_manager._teams:
            return

        for i in range(90):
            await asyncio.sleep(2)
            running = {k: not t.done() for k, t in task_manager._async_tasks.items()}
            completed_ids = [t.id for t in task_manager._tasks.values() if t.status != "running"]
            print(f"[poll {i}] running={running} completed={completed_ids} teams={list(team_manager._teams.keys())} queue_size={task_manager._notify_queue.qsize()}", file=sys.stderr, flush=True)
            notes = drain_notifications()
            if not notes:
                has_running = any(v for v in running.values())
                if not has_running:
                    print(f"[poll {i}] no running tasks, breaking", file=sys.stderr, flush=True)
                    break
                continue
            for note in notes:
                conv.add_system_reminder(note)
            # 后续 team 轮询仍用 run_to_completion，避免重复事件循环
            last_result = await agent.run_to_completion(
                "Teammate notifications received. Process them and continue.", conv
            )
            if is_json:
                emit_json({"type": "assistant", "text": last_result})
            else:
                print(last_result, flush=True)

    async with runtime:
        await run_active_runtime()


def _parse_teammate_flags(args: list[str]) -> tuple[str, str] | None:
    """从 CLI 参数里解析队友 worker 模式。

    仅当首个参数是 --teammate 时返回 (team_name, agent_name)，表示 worker 模式；
    否则返回 None，调用方应启动正常 TUI。格式对齐 build_teammate_cli 的产出：

        --teammate --team-name <t> --agent-name <n>
    """
    if not args or args[0] != "--teammate":
        return None
    team_name = ""
    agent_name = ""
    i = 1
    while i < len(args):
        if args[i] == "--team-name" and i + 1 < len(args):
            team_name = args[i + 1]
            i += 2
            continue
        if args[i] == "--agent-name" and i + 1 < len(args):
            agent_name = args[i + 1]
            i += 2
            continue
        i += 1
    return team_name, agent_name


async def _open_teammate_runtime(
    work_dir: str,
    protocol: str,
    client,
    permission_checker,
    context_window: int,
    instructions_content: str,
    team_manager,
    team_name: str,
    agent_name: str,
    mcp_manager=None,
):
    """创建拥有独立 ExtensionSession 的外部队友 Runtime。

    MCP Tool 仍是运行期动态贡献，由 worker boundary 在 Runtime 激活后注册；但
    manager 自身在这里就交给 runtime-resources 托管，连接失败不会留下失主 client。
    """
    from koko_pi_agent.agent import Agent
    from koko_pi_agent.config import WorktreeConfig
    from koko_pi_agent.extensions import (
        BuiltinRuntimeBindings,
        RuntimeProfile,
        create_builtin_extension_host,
    )
    from koko_pi_agent.runtime import AgentRuntime, AgentRuntimeRequest
    from koko_pi_agent.skills.loader import SkillLoader
    from koko_pi_agent.tools import ToolRegistry
    from koko_pi_agent.worktree import WorktreeManager

    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=WorktreeConfig().symlink_directories,
    )
    skill_loader = SkillLoader(work_dir)
    skill_loader.load_all()

    def create_agent(registry: ToolRegistry) -> Agent:
        return Agent(
            client=client,
            registry=registry,
            protocol=protocol,
            work_dir=work_dir,
            permission_checker=permission_checker,
            context_window=context_window,
            instructions_content=instructions_content,
        )

    def create_bindings(
        agent: Agent,
        registry: ToolRegistry,
    ) -> BuiltinRuntimeBindings:
        return BuiltinRuntimeBindings(
            agent=agent,
            registry=registry,
            protocol=protocol,
            worktree_manager=wt_manager,
            team_manager=team_manager,
            skill_loader=skill_loader,
            team_name=team_name,
            agent_name=agent_name,
            from_agent_id=agent_name,
            mcp_manager=mcp_manager,
        )

    return await AgentRuntime.open(
        AgentRuntimeRequest(
            profile=RuntimeProfile.TEAMMATE_WORKER,
            work_dir=work_dir,
            agent_factory=create_agent,
            bindings_factory=create_bindings,
        ),
        extension_host=create_builtin_extension_host(),
    )


async def _run_teammate(team_name: str, agent_name: str) -> None:
    """把本进程作为已有团队的队友 worker 启动。

    流程：加载 config → 建 LLM client → 建工具集（含 SendMessage）→ 定位团队邮箱
    （lead 已在磁盘上创建）→ 建子 agent → 注册成员名字 → 跑队友主循环，
    首个任务由 lead 在 spawn 前写进邮箱、worker 首次空闲轮询取出。
    """
    from koko_pi_agent.client import create_client, resolve_context_window
    from koko_pi_agent.memory.instructions import load_instructions
    from koko_pi_agent.permissions import (
        DangerousCommandDetector,
        PathSandbox,
        PermissionChecker,
        PermissionMode,
        RuleEngine,
    )
    from koko_pi_agent.teams.manager import TeamManager
    from koko_pi_agent.teams.registry import AgentNameRegistry
    from koko_pi_agent.teams.spawn_inprocess import LEAD_NAME, spawn_inprocess_teammate

    # worker 无 TUI，日志走 stderr，供 tmux/iTerm2 窗格直接显示
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True)

    if not team_name or not agent_name:
        print("--teammate requires --team-name and --agent-name", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    if not config.providers:
        print("No providers configured", file=sys.stderr)
        sys.exit(1)

    provider = config.providers[0]
    client = create_client(provider)
    await resolve_context_window(provider)

    work_dir = os.getcwd()

    # 团队目录由 lead 在磁盘上建好，worker 按团队名加载团队与邮箱
    team_manager = TeamManager()
    team = team_manager.get_team(team_name)
    if team is None:
        print(f"Team '{team_name}' not found", file=sys.stderr)
        sys.exit(1)
    mailbox = team_manager.get_mailbox(team_name)
    if mailbox is None:
        print(f"Mailbox for team '{team_name}' not found", file=sys.stderr)
        sys.exit(1)

    # 名字解析表：登记自己和 lead，便于 SendMessage 按名字投递
    name_registry = AgentNameRegistry.instance()
    name_registry.register(agent_name, agent_name)
    name_registry.register(LEAD_NAME, team.lead_agent_id)

    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(),
        mode=PermissionMode.BYPASS,
    )

    # manager 在 Runtime 打开前创建，使它在连接之前就归 Runtime 所有
    mcp_manager = None
    if config.mcp_servers:
        from koko_pi_agent.mcp import MCPManager

        mcp_manager = MCPManager()
        mcp_manager.load_configs(config.mcp_servers)

    runtime = await _open_teammate_runtime(
        work_dir=work_dir,
        protocol=provider.protocol,
        client=client,
        permission_checker=checker,
        context_window=provider.get_context_window(),
        instructions_content=load_instructions(work_dir),
        team_manager=team_manager,
        team_name=team_name,
        agent_name=agent_name,
        mcp_manager=mcp_manager,
    )
    agent = runtime.agent

    try:
        if mcp_manager is not None:
            try:
                result = await mcp_manager.register_all_tools(runtime.registry)
                for error in result.errors:
                    print(f"MCP warning: {error}", file=sys.stderr)
            except Exception as error:
                print(f"MCP setup failed: {error}", file=sys.stderr)

        # 不传初始 prompt：lead 已把首个任务写进邮箱，主循环首次轮询即可取到，
        # 避免重复注入一条 user 消息。
        print(
            f"[teammate {team_name}/{agent_name}] booted, awaiting tasks",
            file=sys.stderr,
        )
        handle = spawn_inprocess_teammate(
            agent=agent,
            prompt="",
            name=agent_name,
            team_name=team_name,
            mailbox=mailbox,
            # 外部 worker 把 idle 通知写到 lead 实际读取的键，保证回传对得上
            lead_key=team.lead_agent_id,
        )
        try:
            await handle.task
        except (KeyboardInterrupt, asyncio.CancelledError):
            handle.cancel()
    finally:
        # Runtime 关闭会撤销 contribution，然后关闭 MCP manager
        await runtime.aclose()


if __name__ == "__main__":
    main()
