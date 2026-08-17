# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from koko_pi_agent.memory.session import SessionMeta


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.0f}KB"
    return f"{size}B"


def _relative_time(meta: SessionMeta) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    dt = meta.last_active.replace(tzinfo=timezone.utc) if meta.last_active.tzinfo is None else meta.last_active
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} hours ago"
    return f"{secs // 86400} days ago"


class InlineResumeWidget(Vertical, can_focus=True):
    """内联的会话恢复视图。"""

    BINDINGS = [
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "select", "Select", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    class Selected(Message):
        def __init__(self, session_id: str | None) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, sessions: list[SessionMeta], project_name: str = "", **kwargs) -> None:
        super().__init__(id="resume-inline", **kwargs)
        self._sessions = sessions
        self._filtered = list(sessions)
        self._project = project_name
        self._cursor = 0
        self._search = ""


    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), id="resume-content")

    def on_mount(self) -> None:
        self.focus()

    def _build_content(self) -> str:
        lines = []
        total = len(self._sessions)
        showing = len(self._filtered)
        lines.append(f"[dim]Resume session ({showing} of {total})[/]\n")

        if self._search:
            lines.append(f"┌{'─' * 30}┐")
            lines.append(f"│⌕ {self._search:<28}│")
            lines.append(f"└{'─' * 30}┘")
        else:
            lines.append(f"┌{'─' * 30}┐")
            lines.append(f"│[dim]⌕ Search…{'':>20}[/]│")
            lines.append(f"└{'─' * 30}┘")

        if self._project:
            lines.append(f"\n  [dim]{self._project}[/]\n")

        for i, meta in enumerate(self._filtered[:10]):  # 最多显示 10 条
            title = meta.title or "(empty session)"
            if i == self._cursor:
                lines.append(f"[bold cyan]❯[/] [bold]{title}[/]")
            else:
                lines.append(f"  {title}")

            parts = [_relative_time(meta)]
            if hasattr(meta, 'branch') and meta.branch:
                parts.append(meta.branch)
            if hasattr(meta, 'file_size') and meta.file_size:
                parts.append(_format_size(meta.file_size))
            lines.append(f"  [dim]{'  ·  '.join(parts)}[/]")
            lines.append("")

        if showing > 10:
            lines.append(f"  [dim]↓ {showing - 10} more session(s)[/]")

        lines.append("[dim]Type to search · Enter to select · Esc to cancel[/]")
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#resume-content", Static).update(self._build_content())


    def _refilter(self) -> None:
        if not self._search:
            self._filtered = list(self._sessions)
        else:
            s = self._search.lower()
            self._filtered = [
                m for m in self._sessions
                if s in (m.title or "").lower() or s in m.id.lower()
            ]
        self._cursor = 0
        self._refresh()


    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._refresh()

    def action_cursor_down(self) -> None:
        if self._cursor < min(len(self._filtered), 10) - 1:
            self._cursor += 1
            self._refresh()


    def action_select(self) -> None:
        if self._filtered and 0 <= self._cursor < len(self._filtered):
            self.post_message(self.Selected(self._filtered[self._cursor].id))
        else:
            self.post_message(self.Selected(None))

    def action_cancel(self) -> None:
        self.post_message(self.Selected(None))

    def on_key(self, event) -> None:
        key = event.key
        if key == "backspace":
            if self._search:
                self._search = self._search[:-1]
                self._refilter()
            event.stop()
        elif len(key) == 1 and key.isprintable():
            self._search += key
            self._refilter()
            event.stop()
