# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

import asyncio
import logging
import os
import random
import time as _time
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message as TMessage
from textual.widgets import Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from koko_pi_agent.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    HookEvent,
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
from koko_pi_agent.client import (
    AuthenticationError,
    LLMClient,
    LLMError,
    create_client,
    resolve_context_window,
)
from koko_pi_agent.commands import (
    CommandContext,
    CommandRegistry,
    complete,
    parse_command,
)
from koko_pi_agent.commands.completion import CompletionPopup
from koko_pi_agent.commands.handlers import register_all_commands
from koko_pi_agent.config import MCPServerConfig, ProviderConfig
from koko_pi_agent.hooks import HookContext, HookEngine, load_hooks
from koko_pi_agent.conversation import ConversationManager, Message
from koko_pi_agent.mcp import ConnectResult, MCPManager
from koko_pi_agent.memory import (
    MemoryManager,
    Session,
    SessionManager,
    find_relevant_memories,
    generate_session_summary,
    load_instructions,
    make_compact_boundary,
    render_reminder,
)
from koko_pi_agent.mascot_overlay import MascotOverlay
from koko_pi_agent.ui_state import UIStateStore
from koko_pi_agent.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from koko_pi_agent.agents.loader import AgentLoader
from koko_pi_agent.agents.task_manager import TaskManager
from koko_pi_agent.agents.trace import TraceManager
from koko_pi_agent.agents.notification import inject_task_notifications
from koko_pi_agent.commands.handlers.tasks import create_tasks_command
from koko_pi_agent.skills.executor import SkillExecutor
from koko_pi_agent.skills.loader import SkillLoader
from koko_pi_agent.commands.handlers.skill_register import register_skill_commands
from koko_pi_agent.extensions import (
    DEFAULT_CANCEL_TIMEOUT,
    BuiltinRuntimeBindings,
    RuntimeProfile,
    create_builtin_extension_host,
)
from koko_pi_agent.runtime import (
    AgentRuntime,
    AgentRuntimeRequest,
    QueuedRunInput,
    RunFinished,
    RunInputClosedError,
    RunInputDelivered,
    RunInputKind,
    RunInputReceipt,
)
from rich.text import Text as RichText
from textual.theme import Theme
from koko_pi_agent.tools import ToolRegistry
from koko_pi_agent.tools.ask_user import AskUserEvent, AskUserTool
from koko_pi_agent.tools.install_skill import InstallSkillTool
from koko_pi_agent.tools.load_skill import LoadSkill
from koko_pi_agent.worktree.cleanup import start_stale_cleanup_task
from koko_pi_agent.worktree.manager import WorktreeManager
from koko_pi_agent.commands.handlers.worktree import create_worktree_command
from koko_pi_agent.teammate_tree import TeammateTree

if TYPE_CHECKING:
    from koko_pi_agent.askuser_dialog import InlineAskUserWidget
    from koko_pi_agent.permission_dialog import InlinePermissionWidget
    from koko_pi_agent.plan_dialog import InlinePlanWidget

import re

log = logging.getLogger(__name__)

MAX_TRUNCATED_LINES = 20
MAX_AT_REF_BYTES = 10240

APP_NAME = "Koko"

try:
    APP_VERSION = _pkg_version("koko-pi-agent")
except PackageNotFoundError:  # 未安装为包（例如直接从源码目录运行）
    APP_VERSION = "0.0.0"

_AT_REF_RE = re.compile(r"@([\w./_\-]+(?:\.[\w]+)*)")

_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".koko",
    "build",
    ".gradle",
}


def scan_files_for_at(prefix: str, work_dir: str, limit: int = 10) -> list[str]:
    matches: list[str] = []
    base = (
        os.path.join(work_dir, os.path.dirname(prefix)) if "/" in prefix else work_dir
    )
    name_prefix = os.path.basename(prefix).lower()
    if not os.path.isdir(base):
        return matches
    try:
        for entry in sorted(os.listdir(base)):
            if entry in _SKIP_DIRS or entry.startswith("."):
                continue
            if entry.lower().startswith(name_prefix):
                rel = (
                    os.path.join(os.path.dirname(prefix), entry)
                    if "/" in prefix
                    else entry
                )
                if os.path.isdir(os.path.join(base, entry)):
                    rel += "/"
                matches.append(rel)
                if len(matches) >= limit:
                    break
    except OSError:
        pass
    return matches


def expand_at_refs(text: str, work_dir: str) -> str:
    def _replace(m: re.Match) -> str:
        rel_path = m.group(1)
        full_path = os.path.join(work_dir, rel_path)
        if not os.path.isfile(full_path):
            return m.group(0)
        try:
            content = open(full_path, encoding="utf-8", errors="replace").read(
                MAX_AT_REF_BYTES
            )
            return f"[File: {rel_path}]\n```\n{content}\n```"
        except Exception:
            return m.group(0)

    return _AT_REF_RE.sub(_replace, text)


class ChatInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Submit", priority=True),
        Binding("alt+enter", "submit_follow_up", "Follow up", priority=True),
        Binding("shift+enter", "newline", "Newline", priority=True),
        Binding("ctrl+j", "newline", "Newline", priority=True),
        Binding("tab", "complete", "Complete", priority=True),
        Binding("escape", "dismiss_popup", "Dismiss", priority=True),
        Binding("up", "nav_up", "Navigate up", priority=True),
        Binding("down", "nav_down", "Navigate down", priority=True),
    ]

    class Submitted(TMessage):
        def __init__(
            self,
            text: str,
            delivery: RunInputKind = RunInputKind.STEERING,
        ) -> None:
            super().__init__()
            self.text = text
            self.delivery = delivery

    class TabComplete(TMessage):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cursor_blink = True
        self.border_title = " Message "
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""
        self._history_file: Path | None = None

    def load_history(self, work_dir: str) -> None:
        self._history_file = Path(work_dir) / ".koko" / "history"
        if self._history_file.exists():
            try:
                lines = self._history_file.read_text(encoding="utf-8").splitlines()
                self._history = [l for l in lines if l.strip()]
            except Exception:
                pass

    def _persist_entry(self, text: str) -> None:
        if self._history_file is None:
            return
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _popup(self) -> CompletionPopup | None:
        try:
            return self.app.query_one(CompletionPopup)
        except Exception:
            return None

    def action_submit(self) -> None:
        self._submit(RunInputKind.STEERING)

    def action_submit_follow_up(self) -> None:
        self._submit(RunInputKind.FOLLOW_UP)

    def _submit(self, delivery: RunInputKind) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            selected = popup.get_selected()
            popup.hide()
            if selected:
                self._history.append(selected)
                self._persist_entry(selected)
                self._history_index = -1
                self._history_draft = ""
                self.post_message(self.Submitted(selected, delivery))
                self.clear()
                return
        text = self.text.strip()
        if text:
            self._history.append(text)
            self._persist_entry(text)
            self._history_index = -1
            self._history_draft = ""
            self.post_message(self.Submitted(text, delivery))
            self.clear()

    def action_newline(self) -> None:
        self.insert("\n")

    def action_complete(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            selected = popup.get_selected()
            if selected:
                popup.hide()
                self.clear()
                self.insert(selected + " ")
            return
        text = self.text.strip()
        if text.startswith("/"):
            self.post_message(self.TabComplete(text))
        else:
            self.insert("\t")

    def action_dismiss_popup(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.hide()
            return
        try:
            mascot = self.app.query_one(MascotOverlay)
            if mascot.is_open:
                mascot.close_mascot()
        except Exception:
            pass

    def action_nav_up(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.move_up()
            return
        if not self._history:
            return
        if self._history_index == -1:
            self._history_draft = self.text
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return
        self.clear()
        self.insert(self._history[self._history_index])

    def action_nav_down(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.move_down()
            return
        if self._history_index == -1:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.clear()
            self.insert(self._history[self._history_index])
        else:
            self._history_index = -1
            self.clear()
            self.insert(self._history_draft)

    class AtFileRequest(TMessage):
        def __init__(self, prefix: str) -> None:
            super().__init__()
            self.prefix = prefix

    class SlashMenuUpdate(TMessage):
        def __init__(self, prefix: str | None) -> None:
            super().__init__()
            self.prefix = prefix

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = self.text
        if text.startswith("/") and self._history_index < 0:
            prefix = text[1:]
            if " " not in prefix and "\n" not in prefix:
                self.post_message(self.SlashMenuUpdate(prefix))
            else:
                self.post_message(self.SlashMenuUpdate(None))
        else:
            self.post_message(self.SlashMenuUpdate(None))

        at_idx = text.rfind("@")
        if at_idx < 0:
            return
        after = text[at_idx + 1 :]
        if " " in after or "\n" in after:
            return
        if after:
            self.post_message(self.AtFileRequest(after))


class ChatTranscript(VerticalScroll):
    """Scrollable conversation that gives keyboard input back to the composer.

    Textual focuses a scroll view (or a focusable child such as a tool block)
    when it is clicked. Scrolling and expanding content should not leave the
    user typing into nowhere, so a completed click restores the composer when
    it is available. Inline approval/question widgets disable the composer and
    therefore keep their intentional focus.
    """

    def on_click(self) -> None:
        try:
            input_area = self.app.query_one("#input-area", Vertical)
            chat_input = self.app.query_one("#chat-input", ChatInput)
        except Exception:
            return
        if input_area.display and not chat_input.disabled:
            chat_input.focus(scroll_visible=False)


COLLAPSIBLE_TOOLS = {"ReadFile", "Glob", "Grep", "ToolSearch"}


def _is_subagent_tool(tool_name: str) -> bool:
    return tool_name == "Agent"


def _tool_title(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "ReadFile":
        path = os.path.basename(arguments.get("file_path", ""))
        return f"Read {path}" if path else "Read"
    if tool_name == "WriteFile":
        path = os.path.basename(arguments.get("file_path", ""))
        content = arguments.get("content", "")
        lines = content.count("\n") + 1 if content else 0
        return f"Write {path} ({lines} lines)" if path else "Write"
    if tool_name == "EditFile":
        path = os.path.basename(arguments.get("file_path", ""))
        return f"Edit {path}" if path else "Edit"
    if tool_name == "Bash":
        cmd = arguments.get("command", "")
        short = cmd[:50] + "…" if len(cmd) > 50 else cmd
        return f"Bash: {short}" if short else "Bash"
    if tool_name == "Glob":
        return f"Glob: {arguments.get('pattern', '')}"
    if tool_name == "Grep":
        return f"Grep: {arguments.get('pattern', '')}"
    return tool_name


def _format_detail(tool_name: str, arguments: dict[str, Any], output: str) -> str:
    parts: list[str] = []

    if tool_name == "Bash":
        parts.append(f"  IN   {arguments.get('command', '')}")
        parts.append("")
        for line in output.splitlines():
            parts.append(f"  OUT  {line}")
    elif tool_name == "EditFile":
        # EditFile 的 output 是 build_diff() 生成的带行号 diff 文本：
        # "+ " 开头绿色、"- " 开头红色，其余（上下文行/摘要行）走 dim。
        # 转义 Rich markup 特殊字符，避免代码里的方括号被当成标签解析。
        for line in output.splitlines()[:MAX_TRUNCATED_LINES]:
            escaped = escape(line)
            if line.startswith("+ "):
                parts.append(f"  [green]{escaped}[/]")
            elif line.startswith("- "):
                parts.append(f"  [red]{escaped}[/]")
            else:
                parts.append(f"  [dim]{escaped}[/]")
        total = output.count("\n") + 1
        if total > MAX_TRUNCATED_LINES:
            parts.append(f"  [dim]… ({total - MAX_TRUNCATED_LINES} more lines)[/]")
    elif tool_name in ("ReadFile", "WriteFile"):
        parts.append(f"  {arguments.get('file_path', '')}")
        parts.append("")
        for line in output.splitlines()[:MAX_TRUNCATED_LINES]:
            parts.append(f"  {line}")
        total = output.count("\n") + 1
        if total > MAX_TRUNCATED_LINES:
            parts.append(f"  … ({total - MAX_TRUNCATED_LINES} more lines)")
    else:
        for line in output.splitlines()[:MAX_TRUNCATED_LINES]:
            parts.append(f"  {line}")
        total = output.count("\n") + 1
        if total > MAX_TRUNCATED_LINES:
            parts.append(f"  … ({total - MAX_TRUNCATED_LINES} more lines)")

    return "\n".join(parts)


class ToolCallBlock(Static, can_focus=True):
    def __init__(
        self, tool_name: str, arguments: dict[str, Any], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self._arguments = arguments
        self._title = _tool_title(tool_name, arguments)
        self._full_output = ""
        self._is_error = False
        self._elapsed = 0.0
        self._collapsed = True
        self._loading = True
        self._render_loading()

    def _render_loading(self) -> None:
        self.update(f"  ● {self._title} …")
        self.add_class("tool-block-loading")

    def set_result(self, output: str, is_error: bool, elapsed: float) -> None:
        self._full_output = output
        self._is_error = is_error
        self._elapsed = elapsed
        self._loading = False
        self.remove_class("tool-block-loading")
        if is_error:
            self.add_class("tool-block-error")
        # EditFile 的 diff 是最高频需要的信息，默认直接展开，不用等用户点
        # 或按 ctrl+o；其余工具仍然默认折叠，避免刷屏。
        if self.tool_name == "EditFile" and not is_error:
            self._collapsed = False
            self._render_expanded()
        else:
            self._collapsed = True
            self._render_collapsed()

    def _render_collapsed(self) -> None:
        if self._is_error:
            self.update(f"  ✗ {self._title} ({self._elapsed:.1f}s)")
        else:
            self.update(f"  ✓ {self._title} ({self._elapsed:.1f}s)")

    def _render_expanded(self) -> None:
        if self._is_error:
            header = f"  ✗ {self._title} ({self._elapsed:.1f}s)"
        else:
            header = f"  ✓ {self._title} ({self._elapsed:.1f}s)"
        detail = _format_detail(self.tool_name, self._arguments, self._full_output)
        self.update(f"{header}\n{detail}")

    def on_click(self) -> None:
        if self._loading:
            return
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._render_collapsed()
        else:
            self._render_expanded()


_MODE_CYCLE = [
    PermissionMode.DEFAULT,
    PermissionMode.ACCEPT_EDITS,
    PermissionMode.PLAN,
    PermissionMode.BYPASS,
]

_MODE_COLORS = {
    PermissionMode.DEFAULT: "dim",
    PermissionMode.ACCEPT_EDITS: "green",
    PermissionMode.PLAN: "yellow",
    PermissionMode.BYPASS: "red",
}

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _to_past_tense(verb: str) -> str:
    """把现在进行时动词转换为过去式。"""
    if verb.endswith("ing"):
        stem = verb[:-3]
        if stem.endswith("e"):
            return stem + "d"
        if stem and stem[-1] in "atutitet":
            return stem + "ed"
        return stem + "ed"
    return verb + "ed"


THINKING_VERBS = [
    "Accomplishing",
    "Architecting",
    "Baking",
    "Beboppin'",
    "Befuddling",
    "Bloviating",
    "Boogieing",
    "Boondoggling",
    "Bootstrapping",
    "Brewing",
    "Calculating",
    "Canoodling",
    "Caramelizing",
    "Cascading",
    "Cerebrating",
    "Choreographing",
    "Churning",
    "Coalescing",
    "Cogitating",
    "Combobulating",
    "Composing",
    "Computing",
    "Concocting",
    "Considering",
    "Contemplating",
    "Cooking",
    "Crafting",
    "Creating",
    "Crunching",
    "Crystallizing",
    "Cultivating",
    "Deciphering",
    "Deliberating",
    "Dilly-dallying",
    "Discombobulating",
    "Doodling",
    "Elucidating",
    "Enchanting",
    "Envisioning",
    "Fermenting",
    "Finagling",
    "Flambéing",
    "Flibbertigibbeting",
    "Flummoxing",
    "Forging",
    "Frolicking",
    "Gallivanting",
    "Garnishing",
    "Generating",
    "Germinating",
    "Grooving",
    "Harmonizing",
    "Hatching",
    "Honking",
    "Hullaballooing",
    "Ideating",
    "Imagining",
    "Improvising",
    "Incubating",
    "Inferring",
    "Infusing",
    "Kneading",
    "Lollygagging",
    "Manifesting",
    "Marinating",
    "Meandering",
    "Metamorphosing",
    "Mewing",
    "Moonwalking",
    "Moseying",
    "Mulling",
    "Musing",
    "Noodling",
    "Orbiting",
    "Orchestrating",
    "Percolating",
    "Philosophising",
    "Pondering",
    "Pontificating",
    "Pouncing",
    "Purring",
    "Puzzling",
    "Razzle-dazzling",
    "Ruminating",
    "Scampering",
    "Simmering",
    "Sketching",
    "Spelunking",
    "Spinning",
    "Sprouting",
    "Synthesizing",
    "Thinking",
    "Tinkering",
    "Transfiguring",
    "Transmuting",
    "Undulating",
    "Unfurling",
    "Unravelling",
    "Vibing",
    "Wandering",
    "Whisking",
    "Working",
    "Wrangling",
    "Zigzagging",
]  # 共 105 个 TUI 快捷键动词


class ToolGroupSummary(Static, can_focus=True):
    def __init__(self, count: int, total_elapsed: float, **kwargs: Any) -> None:
        label = f"● Done ({count} tool uses · {total_elapsed:.1f}s)  (ctrl+o to expand)"
        super().__init__(label, **kwargs)
        self._count = count
        self._total = total_elapsed
        self._expanded = False

    def _refresh_display(self) -> None:
        if self._expanded:
            self.update(f"▼ Done ({self._count} tool uses · {self._total:.1f}s)")
        else:
            self.update(
                f"● Done ({self._count} tool uses · {self._total:.1f}s)"
                "  (ctrl+o to expand)"
            )

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._refresh_display()

    def on_click(self) -> None:
        self.toggle()


class SubAgentBlock(Static, can_focus=True):
    def __init__(self, agent_type: str, description: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_type = agent_type or "agent"
        self._description = description[:60] if description else ""
        self._done = False
        self._is_error = False
        self._elapsed = 0.0
        self._collapsed = True
        self._result_preview = ""
        self._tool_count = 0
        self._render_running()

    def _render_running(self) -> None:
        desc = f"({self._description})" if self._description else ""
        self.update(f"● {self._agent_type}{desc}\n     Running…")

    def set_result(self, output: str, is_error: bool, elapsed: float) -> None:
        self._done = True
        self._is_error = is_error
        self._elapsed = elapsed
        self._result_preview = output[:300] if output else ""
        self._parse_stats(output)
        self._render_done()

    def _parse_stats(self, output: str) -> None:
        import re

        m = re.search(r"(\d+)\s+tool", output[:200])
        if m:
            self._tool_count = int(m.group(1))

    def _render_done(self) -> None:
        desc = f"({self._description})" if self._description else ""
        tool_info = f"{self._tool_count} tool uses · " if self._tool_count else ""
        if self._collapsed:
            self.update(
                f"● {self._agent_type}{desc}\n"
                f"    ⎿  Done ({tool_info}{self._elapsed:.1f}s)  (ctrl+o to expand)"
            )
        else:
            self.update(
                f"● {self._agent_type}{desc}\n"
                f"    ⎿  Done ({tool_info}{self._elapsed:.1f}s)\n"
                f"  {self._result_preview}"
            )

    def on_click(self) -> None:
        if not self._done:
            return
        self._collapsed = not self._collapsed
        self._render_done()


_KOKO_THEME = Theme(
    name="koko",
    primary="#875FFF",
    background="#1a1a1a",
    surface="#1a1a1a",
    panel="#1a1a1a",
    dark=True,
)


class KokoApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = APP_NAME
    INLINE_PADDING = 0
    AUTO_FOCUS = "#chat-input"
    theme = "koko"
    BINDINGS = [
        Binding("ctrl+c", "handle_ctrl_c", "Quit", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("shift+tab", "cycle_mode", "Cycle mode", priority=True),
        Binding("ctrl+o", "toggle_tool_blocks", "Toggle tools", priority=True),
    ]

    def __init__(
        self,
        providers: list[ProviderConfig],
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        mcp_servers: list[MCPServerConfig] | None = None,
        hook_engine: HookEngine | None = None,
        enable_fork: bool = True,
        enable_verification_agent: bool = False,
        worktree_config: Any = None,
        teammate_mode: str = "",
        enable_coordinator_mode: bool = False,
        driver_class: type | None = None,
        sandbox_config: Any = None,
        ui_state_path: str | Path | None = None,
    ) -> None:
        super().__init__(driver_class=driver_class)
        self.providers = providers
        self._initial_permission_mode = permission_mode
        self._mcp_server_configs = mcp_servers or []
        self.hook_engine = hook_engine
        self._enable_fork = enable_fork
        self._enable_verification_agent = enable_verification_agent
        self._worktree_config = worktree_config
        self._teammate_mode = teammate_mode
        self._enable_coordinator_mode = enable_coordinator_mode
        from koko_pi_agent.config import SandboxAppConfig

        self._sandbox_cfg: SandboxAppConfig = sandbox_config or SandboxAppConfig()
        self._ui_state_store = UIStateStore(ui_state_path)
        self._provider_init_lock = asyncio.Lock()
        self.client: LLMClient | None = None
        self.conversation = ConversationManager()
        self.registry = ToolRegistry()
        self.runtime: AgentRuntime | None = None
        self.agent: Agent | None = None
        self.mcp_manager: MCPManager | None = None
        self._mcp_init_task: asyncio.Task[None] | None = None
        self._selected_provider: ProviderConfig | None = None
        self._streaming = False
        self._thinking_start: float = 0.0
        self._thinking_verb: str = ""
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._spinner_label: Static | None = None
        self._mcp_server_info: str = ""
        self._agent_task: asyncio.Task[None] | None = None
        self._subagent_task: asyncio.Task[None] | None = None
        self._subagent_start_time: float | None = None
        self.session_manager: SessionManager | None = None
        self.session: Session | None = None
        self.memory_manager: MemoryManager | None = None
        self._instructions_content: str = ""
        self.command_registry = CommandRegistry()
        register_all_commands(self.command_registry)
        self.skill_loader: SkillLoader | None = None
        self.skill_executor: SkillExecutor | None = None
        self._load_skill_tool: LoadSkill | None = None
        self._install_skill_tool: InstallSkillTool | None = None
        self.agent_loader: AgentLoader | None = None
        self.task_manager: TaskManager = TaskManager()
        self.trace_manager: TraceManager = TraceManager()
        self._notification_check_task: asyncio.Task[None] | None = None
        self.worktree_manager: WorktreeManager | None = None
        self._current_streaming_label: Static | None = None
        self._current_ai_row: Vertical | None = None
        self._current_accumulated_text: str = ""
        self._mcp_instructions: str = ""
        self._mcp_instructions_ok: bool = False
        self._mcp_connecting: bool = False
        self._teammate_tree: TeammateTree | None = None
        self._teammate_timer = None
        # 记录本次会话是否曾退出过 Plan Mode，用于重入时注入提示
        self._has_exited_plan_mode: bool = False

    @staticmethod
    def _make_banner(model: str = "", work_dir: str = "") -> RichText:
        t = RichText()
        t.append(" /\\_____/\\  ", style="bold color(99)")
        t.append(f"{APP_NAME} v{APP_VERSION}\n", style="color(242)")
        t.append("(  o   o  ) ", style="bold color(99)")
        t.append(f"{model}\n" if model else "\n", style="color(242)")
        t.append(" \\   ^   /  ", style="bold color(99)")
        t.append(work_dir, style="color(242)")
        return t

    def compose(self) -> ComposeResult:
        yield Static(self._make_banner(), id="title-bar")

        if len(self.providers) > 1:
            with Vertical(id="provider-select"):
                yield Static("Select a Provider", id="select-label")
                yield OptionList(
                    *[
                        Option(f"{p.name}  [{p.model}]", id=p.name)
                        for p in self.providers
                    ],
                    id="provider-list",
                )
        yield ChatTranscript(id="chat-area")
        with Vertical(id="input-area"):
            yield ChatInput(id="chat-input")
            with Horizontal(id="status-bar"):
                yield Static("  default", id="mode-label")
                yield Static("", id="teammates-label")
                yield Static("", id="model-label")
            yield CompletionPopup()
        yield MascotOverlay(id="mascot-overlay")

    async def on_mount(self) -> None:
        self.register_theme(_KOKO_THEME)
        self.theme = "koko"
        if len(self.providers) == 1:
            await self._select_provider(self.providers[0])
        else:
            self.query_one("#chat-area").display = False
            self.query_one("#input-area").display = False
            if len(self.providers) > 1:
                self.query_one("#provider-list", OptionList).focus()
        if self._ui_state_store.mascot_open:
            self.query_one(MascotOverlay).show_mascot(focus_close=False)

    async def _select_provider(self, provider: ProviderConfig) -> None:
        async with self._provider_init_lock:
            await self._select_provider_unlocked(provider)

    async def _select_provider_unlocked(self, provider: ProviderConfig) -> None:
        try:
            client = create_client(provider)
        except AuthenticationError as e:
            self._show_error(str(e))
            return

        if self.runtime is not None:
            # 先停掉 App 持有的 MCP 初始化 task，再关 Runtime：
            # manager 与 stale-cleanup 由 runtime-resources 扩展负责关闭。
            await self._stop_mcp_initialization()
            await self._shutdown_runtime()
            # Runtime 已关闭它，别让引用留到下一轮
            self.mcp_manager = None
            if (
                self._notification_check_task is not None
                and not self._notification_check_task.done()
            ):
                self._notification_check_task.cancel()
            self._notification_check_task = None
            if self.session is not None:
                self.session.close()
                self.session = None
            self.command_registry = CommandRegistry()
            register_all_commands(self.command_registry)
            self.task_manager = TaskManager()
            self.trace_manager = TraceManager()

        self._selected_provider = provider
        self.client = client

        work_dir = os.getcwd()
        home = Path.home()
        sandbox_auto_allow = self._sandbox_cfg.enabled and self._sandbox_cfg.auto_allow
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(work_dir),
            rule_engine=RuleEngine(
                user_rules_path=home / ".koko" / "permissions.yaml",
                project_rules_path=Path(work_dir) / ".koko" / "permissions.yaml",
                local_rules_path=Path(work_dir) / ".koko" / "permissions.local.yaml",
            ),
            mode=self._initial_permission_mode,
            sandbox_enabled=sandbox_auto_allow,
        )

        bash_sandbox = None
        bash_sandbox_config = None
        if self._sandbox_cfg.enabled:
            from koko_pi_agent.sandbox import SandboxConfig, create_sandbox

            candidate = create_sandbox()
            if candidate and candidate.available():
                bash_sandbox = candidate
                bash_sandbox_config = SandboxConfig(
                    allow_write=[work_dir, "/tmp"],
                    deny_write=[
                        f"{work_dir}/.koko/config.yaml",
                        f"{work_dir}/.koko/permissions.local.yaml",
                    ],
                    network_enabled=self._sandbox_cfg.network_enabled,
                )

        self._instructions_content = load_instructions(work_dir)
        self.memory_manager = MemoryManager(work_dir)
        self.session_manager = SessionManager(work_dir)
        self.session_manager.cleanup()
        self.session = self.session_manager.create()

        from koko_pi_agent.filehistory import FileHistory

        self.file_history = FileHistory(work_dir, self.session.session_id)
        self.skill_loader = SkillLoader(work_dir)
        self.skill_loader.load_all()

        from koko_pi_agent.config import WorktreeConfig

        wt_cfg = self._worktree_config or WorktreeConfig()
        self.worktree_manager = WorktreeManager(
            repo_root=work_dir,
            symlink_directories=wt_cfg.symlink_directories,
        )
        restored = self.worktree_manager.restore_session()

        self.agent_loader = AgentLoader(
            work_dir, enable_verification=self._enable_verification_agent
        )
        self.agent_loader.load_all()

        from koko_pi_agent.teams.manager import TeamManager

        self.team_manager = TeamManager(
            worktree_manager=self.worktree_manager,
            trace_manager=self.trace_manager,
        )

        def on_skill_installed(_name: str) -> None:
            assert self.skill_loader is not None
            assert self.skill_executor is not None
            register_skill_commands(
                self.command_registry,
                self.skill_loader,
                self.skill_executor,
            )

        def create_agent(registry: ToolRegistry) -> Agent:
            agent = Agent(
                client=self.client,
                registry=registry,
                protocol=provider.protocol,
                work_dir=work_dir,
                permission_checker=checker,
                context_window=provider.get_context_window(),
                instructions_content=self._instructions_content,
                memory_manager=self.memory_manager,
                hook_engine=self.hook_engine,
            )
            agent.file_history = self.file_history
            agent.session_id = self.session.session_id
            if restored:
                agent.work_dir = restored.worktree_path
            return agent

        def create_bindings(
            agent: Agent,
            registry: ToolRegistry,
        ) -> BuiltinRuntimeBindings:
            self.skill_executor = SkillExecutor(
                agent=agent,
                client=self.client,
                protocol=provider.protocol,
            )
            return BuiltinRuntimeBindings(
                agent=agent,
                registry=registry,
                protocol=provider.protocol,
                file_history=self.file_history,
                agent_loader=self.agent_loader,
                task_manager=self.task_manager,
                trace_manager=self.trace_manager,
                provider_config=provider,
                worktree_manager=self.worktree_manager,
                team_manager=self.team_manager,
                skill_loader=self.skill_loader,
                skill_executor=self.skill_executor,
                on_skill_installed=on_skill_installed,
                bash_sandbox=bash_sandbox,
                bash_sandbox_config=bash_sandbox_config,
                enable_fork=self._enable_fork,
                teammate_mode=self._teammate_mode,
                is_interactive=True,
                enable_coordinator_mode=self._enable_coordinator_mode,
                mcp_manager=self.mcp_manager,
                stale_cleanup_factory=lambda: start_stale_cleanup_task(
                    self.worktree_manager,
                    wt_cfg.stale_cleanup_interval,
                    wt_cfg.stale_cutoff_hours,
                ),
            )

        # MCP manager 必须在 Runtime 打开前就有 owner：连接是可失败步骤，
        # 在它被赋值给 self 之前取消会留下无人关闭的 client。
        if self._mcp_server_configs:
            self.mcp_manager = MCPManager()
            self.mcp_manager.load_configs(self._mcp_server_configs)

        self.runtime = await AgentRuntime.open(
            AgentRuntimeRequest(
                profile=RuntimeProfile.TUI_LEAD,
                work_dir=work_dir,
                agent_factory=create_agent,
                bindings_factory=create_bindings,
            ),
            extension_host=create_builtin_extension_host(),
        )
        self.agent = self.runtime.agent
        self.registry = self.runtime.registry
        self._load_skill_tool = self.registry.get("LoadSkill")
        self._install_skill_tool = self.registry.get("InstallSkill")
        self._exit_plan_tool = self.registry.get("ExitPlanMode")

        self.run_worker(
            self._resolve_context_window(provider),
            exclusive=False,
        )

        catalog = self.skill_loader.get_catalog()
        if catalog:
            lines = ["You can use the following Skills:", ""]
            for name, desc in catalog:
                lines.append(f"- {name}: {desc}")
            lines.extend(
                [
                    "",
                    "If the user's request matches a Skill, call LoadSkill to activate it.",
                ]
            )
            self.agent.set_skill_catalog("\n".join(lines))

        assert self.skill_executor is not None
        register_skill_commands(
            self.command_registry,
            self.skill_loader,
            self.skill_executor,
        )

        wt_command = create_worktree_command(self.worktree_manager)
        self.command_registry.register_sync(wt_command)

        agent_catalog = self.agent_loader.list_agents()
        if agent_catalog:
            lines = [
                "## Available Sub-Agent Types",
                "",
                "Use the Agent tool with subagent_type parameter to delegate tasks:",
                "",
            ]
            for agent_type, when_to_use in agent_catalog:
                lines.append(f"- **{agent_type}**: {when_to_use}")
            if self._enable_fork:
                lines.extend(
                    [
                        "",
                        "Leave subagent_type empty to fork the current conversation "
                        "(inherits full dialog history).",
                    ]
                )
            lines.extend(
                [
                    "",
                    "IMPORTANT: Sub-agents run in the background. "
                    "After calling the Agent tool, you will get a task ID immediately. "
                    "Do NOT wait, sleep, or poll for the result. "
                    "Simply report the task ID to the user and end your turn. "
                    "The system will automatically notify when the task completes.",
                ]
            )
            self.agent.set_agent_catalog(
                "\n".join(lines),
                catalog_list=agent_catalog,
            )

        self.command_registry.register_sync(create_tasks_command(self.task_manager))
        from koko_pi_agent.commands.handlers.trace import create_trace_command

        self.command_registry.register_sync(
            create_trace_command(self.trace_manager, self.agent.agent_id)
        )

        if self._enable_coordinator_mode:
            from koko_pi_agent.agents.tool_filter import apply_coordinator_filter

            self.agent.enable_coordinator_mode = True
            self.agent.registry = apply_coordinator_filter(self.agent.registry)
        self.agent._team_manager = self.team_manager

        if self.hook_engine:
            asyncio.ensure_future(
                self.hook_engine.run_hooks(
                    "startup",
                    HookContext(event_name="startup"),
                )
            )
        if self._mcp_server_configs:
            self._mcp_init_task = asyncio.create_task(self._init_mcp())

        self.query_one("#model-label", Static).update(provider.model)
        self.query_one("#title-bar", Static).update(
            self._make_banner(provider.model, work_dir)
        )
        self._update_mode_label()

        select = self.query("#provider-select")
        if select:
            select.first().display = False
        self.query_one("#chat-area").display = True
        self.query_one("#input-area").display = True
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = (
            "Type a message...  Enter to send · Shift+Enter for newline"
        )
        chat_input.load_history(work_dir)
        chat_input.focus()

        self._notification_check_task = asyncio.create_task(
            self._start_notification_polling()
        )

    async def _resolve_context_window(self, provider: ProviderConfig) -> None:
        await resolve_context_window(provider)
        if self.agent is not None:
            self.agent.context_window = provider.get_context_window()

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "provider-list":
            provider = self.providers[event.option_index]
            await self._select_provider(provider)

    # -----------------------------------------------------------------
    # UIController 协议实现
    # -----------------------------------------------------------------

    def add_system_message(self, text: str) -> None:
        self._show_system_message(text)

    def send_user_message(self, text: str) -> None:
        if self.agent is None:
            return
        asyncio.create_task(self._dispatch_command(text))

    async def _render_queued_input(self, receipt: RunInputReceipt) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        user_row = Vertical(classes="user-row")
        await chat.mount(user_row)
        user_rich = RichText()
        user_rich.append("❯ ", style="bold color(80)")
        user_rich.append(receipt.item.text, style="bold color(255)")
        user_rich.append(
            f"  [{receipt.item.kind.value} queued]",
            style="dim color(242)",
        )
        await user_row.mount(Static(user_rich, classes="message user-message"))
        self.call_after_refresh(chat.scroll_end, animate=False)

    def _restore_undelivered_inputs(
        self,
        inputs: tuple[QueuedRunInput, ...],
    ) -> None:
        if not inputs:
            return
        input_widget = self.query_one("#chat-input", ChatInput)
        restored = "\n".join(item.text for item in inputs)
        existing = input_widget.text.strip()
        input_widget.clear()
        input_widget.insert("\n".join(part for part in (restored, existing) if part))
        self._show_system_message(
            f"Restored {len(inputs)} undelivered input(s) to the editor"
        )

    async def _queue_active_input(
        self,
        text: str,
        delivery: RunInputKind,
    ) -> bool:
        runtime = self.runtime
        if runtime is None or not self._streaming:
            return False
        try:
            if delivery is RunInputKind.FOLLOW_UP:
                receipt = runtime.follow_up_active_run(text)
            else:
                receipt = runtime.steer_active_run(text)
        except RunInputClosedError:
            receipt = None
        except RuntimeError as exc:
            self._show_error(str(exc))
            return True
        if receipt is not None:
            await self._render_queued_input(receipt)
            return True

        running_task = self._agent_task
        if (
            running_task is not None
            and running_task is not asyncio.current_task()
            and not running_task.done()
        ):
            await asyncio.shield(running_task)
        return False

    def set_plan_mode(self, enabled: bool) -> None:
        if self.agent is None:
            return
        if enabled:
            self._pre_plan_mode = self.agent.permission_mode
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            restore = getattr(self, "_pre_plan_mode", PermissionMode.DEFAULT)
            self.agent.set_permission_mode(restore)
        self._update_mode_label()

    def get_token_count(self) -> tuple[int, int]:
        if self.agent:
            return self.agent.total_input_tokens, self.agent.total_output_tokens
        return 0, 0

    def refresh_status(self) -> None:
        self._update_mode_label()

    def show_mascot(self) -> None:
        self.query_one(MascotOverlay).show_mascot()
        self._ui_state_store.set_mascot_open(True)

    def on_mascot_overlay_closed(self, _event: MascotOverlay.Closed) -> None:
        """Persist the close and restore focus to the currently visible UI."""
        self._ui_state_store.set_mascot_open(False)
        if len(self.providers) > 1:
            try:
                provider_select = self.query_one("#provider-select", Vertical)
                if provider_select.display:
                    self.query_one("#provider-list", OptionList).focus()
                    return
            except Exception:
                pass
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            if self.query_one("#input-area", Vertical).display:
                chat_input.focus(scroll_visible=False)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # 命令分发
    # -----------------------------------------------------------------

    def _build_command_context(self, args: str) -> CommandContext:
        return CommandContext(
            args=args,
            agent=self.agent,
            conversation=self.conversation,
            session=self.session,
            session_manager=self.session_manager,
            memory_manager=self.memory_manager,
            ui=self,
            config={
                "registry": self.command_registry,
                "set_session": self._set_session,
                "set_conversation": self._set_conversation,
                "clear_chat": self._clear_chat,
                "render_restored": self._render_restored_messages,
                "skill_loader": self.skill_loader,
                "skill_executor": self.skill_executor,
            },
        )

    def _set_session(self, session: Session) -> None:
        self.session = session
        if self.agent:
            self.agent.session_id = session.session_id

    def _persist_compact_boundary(self, notification: CompactNotification) -> None:
        """Layer-2 compact 后写入 compact_boundary 记录。

        将摘要 + 原样保留的尾部内联到一条记录中，resume 时只需这一条
        就能重建压缩后的状态。之前已写入磁盘的原始前缀不会被重放。
        没有活跃 session 或 compact 未产出 boundary 时直接跳过。
        """
        if not self.session or notification.boundary is None:
            return
        record = make_compact_boundary(
            notification.boundary.summary,
            notification.boundary.keep,
        )
        self.session.append_record(record)

    def _set_conversation(self, conv: ConversationManager) -> None:
        self.conversation = conv

    def _clear_chat(self) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        chat.remove_children()

    async def _dispatch_command(
        self,
        text: str,
        delivery: RunInputKind = RunInputKind.STEERING,
    ) -> None:
        name, args, is_command = parse_command(text)

        if not is_command:
            if self.agent is None:
                return
            if self._streaming and await self._queue_active_input(text, delivery):
                return
            self._agent_task = asyncio.create_task(self._send_message(text))
            return

        if name == "":
            commands = self.command_registry.list_commands()
            lines = ["可用命令："]
            for cmd in commands:
                aliases_str = ", ".join(f"/{a}" for a in cmd.aliases)
                name_part = f"/{cmd.name}"
                if aliases_str:
                    name_part += f", {aliases_str}"
                lines.append(f"  {name_part:<24} {cmd.description}")
            self._show_system_message("\n".join(lines))
            return

        cmd = self.command_registry.find(name)
        if cmd is None:
            self._show_system_message(f"未知命令：/{name}，输入 /help 查看可用命令")
            return

        if not args and cmd.arg_prompt:
            self._show_system_message(cmd.arg_prompt)
            return

        ctx = self._build_command_context(args)
        try:
            await cmd.handler(ctx)
        except Exception as e:
            self._show_error(f"命令执行失败: {e}")

    # -----------------------------------------------------------------
    # 输入处理
    # -----------------------------------------------------------------

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.text.strip()
        await self._dispatch_command(text, event.delivery)

    def on_chat_input_tab_complete(self, event: ChatInput.TabComplete) -> None:
        matches = complete(self.command_registry, event.text)
        if not matches:
            return
        popup = self.query_one(CompletionPopup)
        if len(matches) == 1:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert(matches[0][1] + " ")
        else:
            popup.show_pairs(matches)

    def on_chat_input_slash_menu_update(self, event: ChatInput.SlashMenuUpdate) -> None:
        popup = self.query_one(CompletionPopup)
        if event.prefix is None:
            popup.hide()
            return
        matches = complete(self.command_registry, event.prefix)
        if not matches:
            popup.hide()
            return
        popup.show_pairs(matches)

    def on_chat_input_at_file_request(self, event: ChatInput.AtFileRequest) -> None:
        work_dir = self.agent.work_dir if self.agent else os.getcwd()
        matches = scan_files_for_at(event.prefix, work_dir)
        if matches:
            popup = self.query_one(CompletionPopup)
            popup.show([f"@{m}" for m in matches])

    def on_completion_popup_selected(self, event: CompletionPopup.Selected) -> None:
        input_widget = self.query_one("#chat-input", ChatInput)
        selected = event.value
        text = input_widget.text
        if selected.startswith("@"):
            at_idx = text.rfind("@")
            if at_idx >= 0:
                input_widget.clear()
                input_widget.insert(text[:at_idx] + selected + " ")
                input_widget.focus()
                return
        input_widget.clear()
        input_widget.insert(selected + " ")
        input_widget.focus()

    def action_cycle_mode(self) -> None:
        if self.agent is None:
            return
        current = self.agent.permission_mode
        try:
            idx = _MODE_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_mode = _MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)]
        self.agent.set_permission_mode(next_mode)
        self._update_mode_label()

    def action_toggle_tool_blocks(self) -> None:
        for block in self.query(ToolCallBlock):
            if block._loading:
                continue
            block._collapsed = not block._collapsed
            if block._collapsed:
                block._render_collapsed()
            else:
                block._render_expanded()

        for summary in self.query(ToolGroupSummary):
            was_expanded = summary._expanded
            summary.toggle()
            parent = summary.parent
            if parent:
                for child in parent.children:
                    if (
                        isinstance(child, ToolCallBlock)
                        and child.tool_name in COLLAPSIBLE_TOOLS
                    ):
                        child.display = summary._expanded

        for block in self.query(SubAgentBlock):
            if block._done:
                block._collapsed = not block._collapsed
                block._render_done()

    def action_cancel(self) -> None:
        mascot = self.query_one(MascotOverlay)
        if mascot.is_open:
            mascot.close_mascot()
            return
        popup = self.query_one(CompletionPopup)
        if popup.is_visible:
            popup.hide()
            self.query_one("#chat-input", ChatInput).focus()
            return
        if self._agent_task and not self._agent_task.done():
            if self._subagent_task and not self._subagent_task.done():
                task_id = (
                    self.task_manager.adopt_running(
                        self._subagent_task, "background task"
                    )
                    if hasattr(self.task_manager, "adopt_running")
                    else None
                )
                if task_id:
                    self._show_system_message(
                        f"Task moved to background (id: {task_id})"
                    )
                    return
            if self.runtime is not None:
                try:
                    if self.runtime.cancel_active_run():
                        return
                except RuntimeError:
                    return
            self._agent_task.cancel()

    async def _prefetch_relevant_memories(self, query: str) -> str:
        """Run the recall selector as a side-query with an 8s timeout.

        Creates a fresh LLM client so the selector's system prompt is
        independent of the main conversation's system prompt. Returns the
        rendered system-reminder body, or "" on any failure / timeout.
        """
        if self.memory_manager is None or self._selected_provider is None:
            return ""

        provider = self._selected_provider
        user_dir = self.memory_manager.user_mem_dir
        project_dir = self.memory_manager.project_mem_dir

        async def selector(system_prompt: str, user_message: str) -> str:
            from koko_pi_agent.tools.base import StreamEnd, TextDelta

            side_client = create_client(provider)
            mini_conv = ConversationManager()
            mini_conv.history = [Message(role="user", content=user_message)]
            collected = ""
            async for event in side_client.stream(mini_conv, system=system_prompt):
                if isinstance(event, TextDelta):
                    collected += event.text
                elif isinstance(event, StreamEnd):
                    pass
            return collected

        try:
            results = await asyncio.wait_for(
                find_relevant_memories(
                    query=query,
                    user_mem_dir=user_dir,
                    project_mem_dir=project_dir,
                    recent_tools=None,
                    already_surfaced=None,
                    selector=selector,
                ),
                timeout=8.0,
            )
            return render_reminder(results)
        except (asyncio.TimeoutError, Exception):
            return ""

    def _refresh_skills_if_needed(self) -> None:
        """每轮对话前检查 skill 目录 modtime，有变化则自动 reload。"""
        if self.skill_loader is None or self.agent is None:
            return
        if not self.skill_loader.needs_reload():
            return
        self.skill_loader.reload()
        if self.command_registry is not None:
            from koko_pi_agent.commands.handlers.skill_register import register_skill_commands

            register_skill_commands(
                self.command_registry, self.skill_loader, self.skill_executor
            )
        catalog = self.skill_loader.get_catalog()
        if catalog:
            lines = ["You can use the following Skills:", ""]
            for name, desc in catalog:
                lines.append(f"- {name}: {desc}")
            lines.append("")
            lines.append(
                "If the user's request matches a Skill, call LoadSkill to activate it."
            )
            self.agent.set_skill_catalog("\n".join(lines))
        else:
            self.agent.set_skill_catalog("")

    async def _send_message(self, text: str, is_notification: bool = False) -> None:
        assert self.agent is not None
        self._refresh_skills_if_needed()

        if self._mcp_init_task and not self._mcp_init_task.done():
            self._show_system_message("Waiting for MCP servers to connect...")
            await self._mcp_init_task

        self._streaming = True
        chat = self.query_one("#chat-area", VerticalScroll)
        input_widget = self.query_one("#chat-input", ChatInput)

        if text and "@" in text:
            text = expand_at_refs(text, self.agent.work_dir)

        # Start memory recall prefetch before UI work.
        prefetch_task = (
            asyncio.create_task(self._prefetch_relevant_memories(text))
            if text
            else None
        )

        if text:
            user_row = Vertical(classes="user-row")
            await chat.mount(user_row)
            from rich.text import Text as RichText

            user_rich = RichText()
            user_rich.append("❯ ", style="bold color(80)")
            user_rich.append(text, style="bold color(255)")
            user_bubble = Static(user_rich, classes="message user-message")
            await user_row.mount(user_bubble)
            self.call_after_refresh(chat.scroll_end, animate=False)

            self.conversation.add_user_message(text)
            if self.session:
                self.session.append(Message(role="user", content=text))

        if self._mcp_instructions and not self._mcp_instructions_ok:
            self.conversation.add_system_reminder(self._mcp_instructions)
            self._mcp_instructions_ok = True

        # 非阻塞 memory recall：传给 agent，工具执行后注入
        if prefetch_task is not None:
            self.agent.memory_recall_task = prefetch_task
            self.agent._memory_recall_consumed = False

        history_anchor = (
            self.conversation.history[-1] if self.conversation.history else None
        )

        def flush_history_tail() -> None:
            nonlocal history_anchor
            if self.session is None:
                return
            start = 0
            if history_anchor is not None:
                start = next(
                    (
                        index + 1
                        for index, message in enumerate(self.conversation.history)
                        if message is history_anchor
                    ),
                    len(self.conversation.history),
                )
            for message in self.conversation.history[start:]:
                self.session.append(message)
            if self.conversation.history:
                history_anchor = self.conversation.history[-1]

        # 准备 AI 回复区域
        ai_row = Vertical(classes="ai-row")
        await chat.mount(ai_row)
        streaming_label = Static("", classes="message ai-message")
        await ai_row.mount(streaming_label)

        accumulated_text = ""
        tool_blocks: dict[str, ToolCallBlock] = {}

        # 在聊天区底部启动持续旋转的加载动画
        self._thinking_start = _time.monotonic()
        self._thinking_verb = random.choice(THINKING_VERBS)
        self._spinner_idx = 0
        self._spinner_label = Static(
            f"  {SPINNER_FRAMES[0]} {self._thinking_verb}…",
            id="spinner-live",
        )
        await chat.mount(self._spinner_label)

        # Mount teammate tree (initially hidden) below the spinner
        self._teammate_tree = TeammateTree(id="teammate-tree")
        self._teammate_tree.display = False
        await chat.mount(self._teammate_tree)
        self._start_teammate_polling()

        self.call_after_refresh(chat.scroll_end, animate=False)
        self._start_spinner()

        await asyncio.sleep(0)

        try:
            async for event in self.agent.run(self.conversation):
                if isinstance(event, ThinkingText):
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, StreamText):
                    if streaming_label is not None and not accumulated_text:
                        await streaming_label.remove()
                        streaming_label = Static("", classes="message ai-message")
                        await ai_row.mount(streaming_label)
                    accumulated_text += event.text
                    from rich.text import Text as RichText

                    t = RichText()
                    t.append("● ", style="bold color(99)")
                    t.append(accumulated_text)
                    streaming_label.update(t)
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, RetryEvent):
                    self._show_system_message(f"↻ Retrying: {event.reason}")

                elif isinstance(event, ToolUseEvent):
                    if accumulated_text:
                        if streaming_label is not None:
                            await streaming_label.remove()
                        from rich.text import Text as RichText

                        prefix = Static(
                            RichText("●  ", style="bold color(99)"), classes="message"
                        )
                        await ai_row.mount(prefix)
                        md = Markdown(accumulated_text, classes="message ai-message")
                        await ai_row.mount(md)
                        streaming_label = None
                        accumulated_text = ""
                    elif streaming_label is not None:
                        await streaming_label.remove()
                        streaming_label = None

                    if _is_subagent_tool(event.tool_name):
                        agent_type = event.arguments.get("subagent_type", "")
                        desc = event.arguments.get("description", "")
                        block = SubAgentBlock(
                            agent_type or "agent",
                            desc,
                            classes="tool-block subagent-block",
                        )
                    else:
                        block = ToolCallBlock(
                            event.tool_name, event.arguments, classes="tool-block"
                        )
                    await ai_row.mount(block)
                    tool_blocks[event.tool_id] = block
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, PermissionRequest):
                    await self._handle_permission_request(event)

                elif isinstance(event, ToolResultEvent):
                    block = tool_blocks.get(event.tool_id)
                    if block:
                        block.set_result(event.output, event.is_error, event.elapsed)
                    self.call_after_refresh(chat.scroll_end, animate=False)

                    ask_tool = self.registry.get("AskUserQuestion")
                    if (
                        ask_tool
                        and isinstance(ask_tool, AskUserTool)
                        and ask_tool._pending_event
                    ):
                        await self._handle_askuser(ask_tool._pending_event)

                elif isinstance(event, TurnComplete):
                    flush_history_tail()

                    collapsible = [
                        (tid, blk)
                        for tid, blk in tool_blocks.items()
                        if isinstance(blk, ToolCallBlock)
                        and blk.tool_name in COLLAPSIBLE_TOOLS
                        and not blk._loading
                    ]
                    if len(collapsible) >= 2:
                        total_elapsed = sum(b._elapsed for _, b in collapsible)
                        summary = ToolGroupSummary(
                            len(collapsible),
                            total_elapsed,
                            classes="tool-block tool-group-summary",
                        )
                        for _, blk in collapsible:
                            blk.display = False
                        await ai_row.mount(summary)

                    tool_blocks.clear()
                    if event.will_continue:
                        ai_row = Vertical(classes="ai-row")
                        await chat.mount(ai_row)
                        streaming_label = Static("", classes="message ai-message")
                        await ai_row.mount(streaming_label)
                        accumulated_text = ""
                        self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, RunInputDelivered):
                    self._show_system_message(
                        f"Delivered {len(event.input_ids)} {event.kind.value} input(s)"
                    )

                elif isinstance(event, UsageEvent):
                    pass  # token 展示已移除

                elif isinstance(event, HookEvent):
                    status = "✓" if event.success else "✗"
                    self._show_system_message(
                        f"Hook [{event.hook_id}] {status} {event.output}"
                    )

                elif isinstance(event, CompactNotification):
                    self._show_system_message(event.message)
                    # auto_compact 已重写 conversation.history（摘要 +
                    # boundary + 保留尾部）。先持久化 boundary 记录，然后
                    # 将游标推进到重建后的历史末尾，这样 TurnComplete/LoopComplete
                    # 刷盘时只追加 boundary 之后的新消息，不会把已压缩的
                    # 前缀作为普通记录重复写入。
                    self._persist_compact_boundary(event)
                    history_anchor = (
                        self.conversation.history[-1]
                        if self.conversation.history
                        else None
                    )

                elif isinstance(event, ErrorEvent):
                    # 保留错误前已输出的流式文本
                    if accumulated_text and streaming_label is not None:
                        await streaming_label.remove()
                        md = Markdown(accumulated_text, classes="message ai-message")
                        await ai_row.mount(md)
                        streaming_label = None
                        accumulated_text = ""
                    self._show_error(event.message)

                elif isinstance(event, LoopComplete):
                    total_time = _time.monotonic() - self._thinking_start
                    done_label = Static(
                        f"✻ {_to_past_tense(self._thinking_verb)} for {total_time:.1f}s",
                        classes="message thinking-done",
                    )
                    await ai_row.mount(done_label)
                    if self.session:
                        flush_history_tail()
                        self.session.meta.total_tokens = (
                            self.agent.total_input_tokens
                            + self.agent.total_output_tokens
                        )
                        asyncio.ensure_future(self._update_session_summary())
                    if self.agent.plan_mode:
                        asyncio.ensure_future(self._show_plan_approval())

                elif isinstance(event, RunFinished):
                    flush_history_tail()
                    self._restore_undelivered_inputs(event.result.undelivered_inputs)

            # 收尾：渲染剩余的累积文本
            if accumulated_text and streaming_label is not None:
                await streaming_label.remove()
                md = Markdown(accumulated_text, classes="message ai-message")
                await ai_row.mount(md)
            elif streaming_label is not None:
                await streaming_label.remove()

            self.call_after_refresh(chat.scroll_end, animate=False)

        except asyncio.CancelledError:
            if accumulated_text:
                if streaming_label is not None:
                    await streaming_label.remove()
                md = Markdown(
                    accumulated_text + "\n\n*[cancelled]*",
                    classes="message ai-message",
                )
                await ai_row.mount(md)
            self._show_system_message("Operation cancelled")
        except LLMError as e:
            self._show_error(str(e))
        finally:
            self._finish_streaming()
            input_widget.focus()

            await self._process_task_notifications()

    async def _process_task_notifications(self) -> None:
        completed = self.task_manager.poll_completed()
        if not completed or self.agent is None:
            return

        inject_task_notifications(self.conversation, completed)

        for task in completed:
            status_icon = "✓" if task.status == "completed" else "✗"
            self._show_system_message(
                f"{status_icon} 后台任务完成: [{task.id}] {task.name} — {task.status}"
            )

            if hasattr(self, "team_manager"):
                self.team_manager.on_teammate_completed(task.agent.agent_id)

        self._agent_task = asyncio.create_task(
            self._send_message("", is_notification=True)
        )

    async def _start_notification_polling(self) -> None:
        while True:
            await asyncio.sleep(2)
            if not self._streaming and self.agent is not None:
                await self._process_task_notifications()
                await self._process_mailbox_notifications()

    async def _process_mailbox_notifications(self) -> None:
        if not hasattr(self, "team_manager") or self.team_manager is None:
            return
        if self._streaming or self.agent is None:
            return
        notes = self.team_manager.drain_lead_mailbox()
        if not notes:
            return
        for note in notes:
            self.conversation.add_system_reminder(note)
        self._agent_task = asyncio.create_task(
            self._send_message("", is_notification=True)
        )

    async def _show_plan_approval(self) -> None:
        from koko_pi_agent.plan_dialog import InlinePlanWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlinePlanWidget()
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_plan_widget_responded(
        self, event: "InlinePlanWidget.Responded"
    ) -> None:
        from koko_pi_agent.plan_dialog import InlinePlanWidget, PlanChoice
        from koko_pi_agent.prompts import build_plan_mode_exit_reminder

        try:
            self.query_one("#plan-inline", InlinePlanWidget).remove()
        except Exception:
            pass
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

        if self.agent is None:
            return

        choice = event.choice
        feedback = event.feedback
        plan_path = self.agent._get_plan_path()
        plan_exists = plan_path.exists()
        plan_content = ""
        if plan_exists:
            try:
                plan_content = plan_path.read_text(encoding="utf-8")
            except Exception:
                pass

        pre = getattr(self, "_pre_plan_mode", PermissionMode.DEFAULT)
        if choice == PlanChoice.YOLO:
            self.agent.set_permission_mode(PermissionMode.BYPASS)
            self._update_mode_label()
            # 构建退出提示并标记已退出 Plan Mode
            exit_msg = build_plan_mode_exit_reminder(str(plan_path), plan_exists)
            self._has_exited_plan_mode = True
            execute_text = (
                exit_msg + "\n\nUser has approved your plan. You can now start coding."
            )
            if plan_content:
                execute_text += "\n\nApproved Plan:\n" + plan_content
            self.send_user_message(execute_text)
        elif choice == PlanChoice.MANUAL:
            self.agent.set_permission_mode(pre)
            self._update_mode_label()
            # 构建退出提示并标记已退出 Plan Mode
            exit_msg = build_plan_mode_exit_reminder(str(plan_path), plan_exists)
            self._has_exited_plan_mode = True
            execute_text = (
                exit_msg + "\n\nUser has approved your plan. You can now start coding."
            )
            if plan_content:
                execute_text += "\n\nApproved Plan:\n" + plan_content
            self.send_user_message(execute_text)
        elif choice == PlanChoice.FEEDBACK:
            if feedback:
                self.send_user_message(feedback)
            else:
                self._show_system_message("Type your feedback and send.")

    async def _handle_askuser(self, event: AskUserEvent) -> None:
        from koko_pi_agent.askuser_dialog import InlineAskUserWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlineAskUserWidget(event.questions)
        self._pending_askuser_event = event
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_ask_user_widget_responded(
        self, event: "InlineAskUserWidget.Responded"
    ) -> None:
        from koko_pi_agent.askuser_dialog import InlineAskUserWidget

        req = getattr(self, "_pending_askuser_event", None)
        if req is not None and not req.future.done():
            req.future.set_result(event.answers if event.answers else {})
            self._pending_askuser_event = None
        try:
            self.query_one("#askuser-inline", InlineAskUserWidget).remove()
        except Exception:
            pass
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def _start_spinner(self) -> None:
        """启动 braille spinner 动画（每帧 80ms）。"""
        if self._spinner_timer is not None:
            return
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _stop_spinner(self) -> None:
        """停止 spinner 动画。"""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _finish_streaming(self) -> None:
        """清理所有 streaming 状态（取消或完成时调用）。"""
        self._streaming = False
        self._stop_spinner()
        self._stop_teammate_polling()
        self._agent_task = None
        if self._teammate_tree is not None:
            self._teammate_tree.remove()
            self._teammate_tree = None
        if self._spinner_label is not None:
            self._spinner_label.remove()
            self._spinner_label = None

    def _tick_spinner(self) -> None:
        """推进持久 spinner 标签上的动画帧。"""
        self._spinner_idx += 1
        frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        elapsed = _time.monotonic() - self._thinking_start
        if self._spinner_label is not None:
            self._spinner_label.update(
                f"  {frame} {self._thinking_verb}…  ({elapsed:.0f}s)"
            )
            if self._spinner_idx % 5 == 0:
                try:
                    self.query_one("#chat-area", VerticalScroll).scroll_end(
                        animate=False
                    )
                except Exception:
                    pass

    def _start_teammate_polling(self) -> None:
        """Start polling teammate progress every 0.5s."""
        if self._teammate_timer is not None:
            return
        self._teammate_timer = self.set_interval(0.5, self._tick_teammate_tree)

    def _stop_teammate_polling(self) -> None:
        """Stop the teammate progress polling timer."""
        if self._teammate_timer is not None:
            self._teammate_timer.stop()
            self._teammate_timer = None

    def _tick_teammate_tree(self) -> None:
        """Poll team_manager for teammate progress and update the tree widget."""
        if not hasattr(self, "team_manager") or self.team_manager is None:
            return
        if self._teammate_tree is None:
            return

        progress_list = self.team_manager.get_all_teammate_progress()

        if not progress_list:
            self._teammate_tree.display = False
            self._update_teammates_label(0)
            return

        # Update the reactive properties via mutate_reactive for list
        self._teammate_tree.teammates = list(progress_list)

        # Update leader tokens from main agent
        if self.agent:
            self._teammate_tree.leader_tokens = (
                self.agent.total_input_tokens + self.agent.total_output_tokens
            )

        self._teammate_tree.display = True
        active_count = sum(1 for p in progress_list if p.status == "running")
        self._update_teammates_label(active_count)

    def _update_teammates_label(self, count: int) -> None:
        """Update the teammates count in the status bar."""
        try:
            label = self.query_one("#teammates-label", Static)
            if count > 0:
                label.update(
                    f"[cyan]● {count} teammate{'s' if count != 1 else ''}[/cyan]  "
                )
            else:
                label.update("")
        except Exception:
            pass

    async def _handle_permission_request(self, request: PermissionRequest) -> None:
        from koko_pi_agent.permission_dialog import InlinePermissionWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlinePermissionWidget(request.tool_name, request.description)
        self._pending_perm_request = request
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        # 权限提示弹窗期间禁用输入框
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_permission_widget_responded(
        self, event: "InlinePermissionWidget.Responded"
    ) -> None:
        from koko_pi_agent.permission_dialog import InlinePermissionWidget

        req = getattr(self, "_pending_perm_request", None)
        if req is not None:
            req.future.set_result(event.response)
            self._pending_perm_request = None
        # 从聊天区移除权限弹窗组件
        try:
            widget = self.query_one("#perm-inline", InlinePermissionWidget)
            widget.remove()
        except Exception:
            pass
        # 重新启用输入框
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    # -----------------------------------------------------------------
    # 恢复 session 的消息渲染
    # -----------------------------------------------------------------

    async def _render_restored_messages(self, messages: list[Message]) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        await chat.remove_children()

        for msg in messages:
            if msg.tool_results or not msg.content:
                continue
            if msg.role == "user":
                row = Vertical(classes="user-row")
                await chat.mount(row)
                user_rich = RichText()
                user_rich.append("❯ ", style="bold color(80)")
                user_rich.append(msg.content, style="bold color(255)")
                bubble = Static(user_rich, classes="message user-message")
                await row.mount(bubble)
            elif msg.role == "assistant":
                row = Vertical(classes="ai-row")
                await chat.mount(row)
                md = Markdown(msg.content, classes="message ai-message")
                await row.mount(md)

        self.call_after_refresh(chat.scroll_end, animate=False)

    # -----------------------------------------------------------------
    # Session 摘要（异步后台生成）
    # -----------------------------------------------------------------

    async def _update_session_summary(self) -> None:
        if not self.session or not self.client or not self.agent:
            return
        try:
            summary = await generate_session_summary(
                self.client, self.conversation, self.agent.protocol
            )
            if summary:
                self.session.meta.summary = summary
                self.session.meta.save(
                    self.session._sessions_dir / f"{self.session.session_id}.meta"
                )
        except Exception:
            pass

    # -----------------------------------------------------------------
    # MCP
    # -----------------------------------------------------------------

    async def _init_mcp(self) -> None:
        """连接所有配置的 MCP 服务器，注册工具。

        manager 由 `_select_provider_unlocked` 在 Runtime 打开前创建并交给
        `koko_pi_agent.runtime-resources` 托管，这里只做连接。
        """
        manager = self.mcp_manager
        if manager is None:
            return

        self._mcp_connecting = True
        self._update_mode_label()
        tools_before = len(self.registry.list_tools())
        connect_result: ConnectResult = await manager.register_all_tools(self.registry)
        self._mcp_connecting = False
        self._update_mode_label()
        for err in connect_result.errors:
            self._show_system_message(f"MCP warning: {err}")
        tools_after = len(self.registry.list_tools())
        mcp_tools = tools_after - tools_before
        server_count = len(connect_result.servers)
        if server_count > 0:
            self._mcp_server_info = f"Connected to {server_count} MCP server(s), {mcp_tools} tools registered"
        if server_count > 0 and mcp_tools > 0:
            # 构建 MCP 指令，从 InitializeResult 提取 instructions
            parts = []
            for srv_info in connect_result.servers:
                section = f"## {srv_info.name}\n"
                # 优先使用服务器返回的 instructions
                if srv_info.instructions:
                    section += srv_info.instructions
                else:
                    # 回退：列出该服务器注册的工具名
                    tool_names = [
                        t.name
                        for t in self.registry.list_tools()
                        if t.name.startswith(f"mcp__{srv_info.name}__")
                    ]
                    if tool_names:
                        section += "Available tools: " + ", ".join(tool_names)
                parts.append(section)
            self._mcp_instructions = (
                "# MCP Server Instructions\n\n"
                "The following MCP servers have provided instructions "
                "for how to use their tools and resources:\n\n" + "\n\n".join(parts)
            )

    async def _stop_mcp_initialization(self) -> None:
        """取消并等待 App 持有的 MCP 初始化 task。

        只负责停止连接动作；manager 与它的 client 由 runtime-resources 扩展在
        Runtime 关闭时释放，所以这里不再 shutdown manager。
        用 asyncio.wait 而不是 await task：后者会把本协程自身的取消一并吞掉。
        """
        task = self._mcp_init_task
        if task is None:
            return
        self._mcp_init_task = None
        if task.done():
            return

        task.cancel()
        _, still_pending = await asyncio.wait([task], timeout=DEFAULT_CANCEL_TIMEOUT)
        if still_pending:
            log.warning(
                "MCP initialization ignored cancellation for %ss",
                DEFAULT_CANCEL_TIMEOUT,
            )

    async def _shutdown_runtime(self) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        await runtime.aclose()
        self.runtime = None

    # -----------------------------------------------------------------
    # 退出
    # -----------------------------------------------------------------

    async def action_handle_ctrl_c(self) -> None:
        if self._streaming:
            if self.runtime is not None:
                try:
                    if self.runtime.cancel_active_run():
                        self._show_system_message("(response interrupted)")
                        return
                except RuntimeError:
                    return
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
            self._show_system_message("(response interrupted)")
            self._finish_streaming()
            try:
                inp = self.query_one("#chat-input", ChatInput)
                inp.disabled = False
                inp.focus()
            except Exception:
                pass
            return

        if getattr(self, "_exit_requested", False):
            self.exit()
            return
        self._exit_requested = True

        async def _cleanup() -> None:
            tasks: list[asyncio.Task] = []

            if self.agent and self.agent.memory_manager:
                tasks.append(
                    asyncio.create_task(self.agent._extract_memories(self.conversation))
                )
            if self.hook_engine:
                tasks.append(
                    asyncio.create_task(
                        self.hook_engine.run_hooks(
                            "shutdown", HookContext(event_name="shutdown")
                        )
                    )
                )
            if tasks:
                await asyncio.wait(tasks, timeout=3.0)
                for t in tasks:
                    if not t.done():
                        t.cancel()

            # 顺序不能反：先停连接动作，再关 Runtime，
            # 由它撤销 contribution 并取消/等待 MCP manager 与 stale-cleanup。
            await self._stop_mcp_initialization()
            await self._shutdown_runtime()
            self.mcp_manager = None

            if hasattr(self, "team_manager"):
                for name in list(self.team_manager._teams):
                    try:
                        team = self.team_manager._teams[name]
                        for m in team.members:
                            team.set_member_active(m.name, False)
                        self.team_manager.delete_team(name)
                    except Exception:
                        pass

            if self.session:
                self.session.close()

        try:
            await _cleanup()
        except Exception:
            pass
        self.exit()

    def _show_error(self, text: str) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        error_widget = Static(f"✖ {text}", classes="message error-message")
        chat.mount(error_widget)
        self.call_after_refresh(chat.scroll_end, animate=False)

    def _show_system_message(self, text: str) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        msg = Static(f"  {text}", classes="message system-message")
        chat.mount(msg)
        self.call_after_refresh(chat.scroll_end, animate=False)

    _MODE_DISPLAY = {
        PermissionMode.DEFAULT: "default",
        PermissionMode.ACCEPT_EDITS: "accept-edits",
        PermissionMode.PLAN: "plan",
        PermissionMode.BYPASS: "YOLO",
    }

    def _update_mode_label(self) -> None:
        if self.agent:
            perm = self.agent.permission_mode
            display = self._MODE_DISPLAY.get(perm, perm.value)
            color = _MODE_COLORS.get(perm, "dim")
            label = self.query_one("#mode-label", Static)
            if perm == PermissionMode.DEFAULT:
                label.update(f"[{color}]{display}[/{color}]")
            else:
                label.update(f"[{color}]{display}[/{color}]  (shift+tab to cycle)")
        try:
            model_label = self.query_one("#model-label", Static)
            model_text = (
                self._selected_provider.model if self._selected_provider else ""
            )
            if self._mcp_connecting:
                model_label.update(f"[yellow]MCP connecting…[/yellow]  {model_text}")
            else:
                model_label.update(model_text)
        except Exception:
            pass

    def _update_token_label(self, input_tokens: int, output_tokens: int) -> None:
        pass  # token 标签已从 UI 中移除
