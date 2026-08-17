# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


class InlineAskUserWidget(Vertical, can_focus=True):
    """内联的 AskUser 组件，支持多问题之间的 Tab 切换导航。

    带 ☐/☑ 勾选标记的导航栏、光标导航、
    多选（MultiSelect）切换、"Other" 自定义输入，以及复核/提交视图。
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "select", "Select", priority=True),
        Binding("tab", "next_q", "Next", priority=True),
        Binding("shift+tab", "prev_q", "Prev", priority=True),
        Binding("space", "toggle", "Toggle", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    class Responded(Message):
        def __init__(self, answers: dict[str, str] | None) -> None:
            super().__init__()
            self.answers = answers


    def __init__(self, questions: list[dict], **kwargs) -> None:
        super().__init__(id="askuser-inline", **kwargs)
        self._questions = questions
        self._q_idx = 0
        n = len(questions)
        self._cursors = [0] * n
        self._selected: list[dict[int, bool]] = [{} for _ in range(n)]
        self._others = [""] * n
        self._answered: dict[int, str] = {}
        self._on_submit = False
        self._submit_idx = 0


    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), id="askuser-content")

    def on_mount(self) -> None:
        self.focus()

    def _option_count(self, q_idx: int) -> int:
        return len(self._questions[q_idx].get("options", [])) + 1  # +1 是为 Other 选项预留的

    def _build_content(self) -> str:
        if self._on_submit:
            return self._render_submit()
        return self._render_question()

    def _render_question(self) -> str:
        lines = []
        multi = len(self._questions) > 1

        if multi:
            nav = self._render_nav_bar()
            lines.append(nav)
            lines.append("")

        q = self._questions[self._q_idx]
        header = q.get("question", q.get("message", f"Question {self._q_idx + 1}"))
        lines.append(f" [bold color(99)]{header}[/]\n")

        options = q.get("options", [])
        is_multi = q.get("multiSelect", False)
        cursor = self._cursors[self._q_idx]

        for i, opt in enumerate(options):
            label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
            desc = opt.get("description", "") if isinstance(opt, dict) else ""

            prefix = " ❯ " if i == cursor else "   "
            bold = "[bold]" if i == cursor else ""
            end_bold = "[/]" if i == cursor else ""

            if is_multi:
                check = "● " if self._selected[self._q_idx].get(i) else "○ "
            else:
                check = ""

            desc_part = f" — [dim]{desc}[/]" if desc else ""
            lines.append(f"{prefix}{check}{bold}{label}{end_bold}{desc_part}")

        # "Other" 选项
        other_idx = len(options)
        prefix = " ❯ " if cursor == other_idx else "   "
        bold = "[bold]" if cursor == other_idx else ""
        end_bold = "[/]" if cursor == other_idx else ""
        lines.append(f"{prefix}{bold}Other{end_bold}")

        if cursor == other_idx:
            text = self._others[self._q_idx]
            display = text if text else "[dim]Type your answer here...[/]"
            lines.append(f"      {display}█")

        if is_multi:
            lines.append("\n      [dim]space to toggle, enter to confirm[/]")
        else:
            lines.append("\n      [dim]enter to confirm[/]")

        return "\n".join(lines)

    def _render_nav_bar(self) -> str:
        parts = []
        for i, q in enumerate(self._questions):
            header = q.get("header", f"Q{i+1}")
            check = "☑" if i in self._answered else "☐"
            if i == self._q_idx and not self._on_submit:
                parts.append(f"[bold reverse] {header} {check} [/]")
            else:
                parts.append(f" {header} {check} ")
        submit_part = "[bold reverse] ✓ Submit [/]" if self._on_submit else " ✓ Submit "
        parts.append(submit_part)
        left = "[bold]←[/]" if self._q_idx > 0 else "[dim]←[/]"
        right = "[bold]→[/]"
        return f" {left} {'|'.join(parts)} {right}"

    def _render_submit(self) -> str:
        lines = ["\n [bold color(99)]Review your answers:[/]\n"]
        for i, q in enumerate(self._questions):
            header = q.get("header", q.get("question", f"Q{i+1}"))
            ans = self._answered.get(i, "")
            if ans:
                lines.append(f"   {header}: {ans}")
            else:
                lines.append(f"   {header}: [dim](not answered)[/]")
        lines.append("")
        for j, label in enumerate(["Submit answers", "Cancel"]):
            if j == self._submit_idx:
                lines.append(f" [bold cyan]❯[/] [bold]{label}[/]")
            else:
                lines.append(f"   [dim]{label}[/]")
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#askuser-content", Static).update(self._build_content())

    def _save_current_answer(self) -> None:
        q = self._questions[self._q_idx]
        options = q.get("options", [])
        cursor = self._cursors[self._q_idx]
        is_multi = q.get("multiSelect", False)

        if cursor == len(options):  # "Other"（自定义输入）
            self._answered[self._q_idx] = self._others[self._q_idx] or "Other"
        elif is_multi:
            selected = [
                (opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt))
                for i, opt in enumerate(options)
                if self._selected[self._q_idx].get(i)
            ]
            if not selected:
                opt = options[cursor]
                selected = [opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)]
            self._answered[self._q_idx] = ", ".join(selected)
        else:
            opt = options[cursor]
            self._answered[self._q_idx] = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)

    def action_cursor_up(self) -> None:
        if self._on_submit:
            if self._submit_idx > 0:
                self._submit_idx -= 1
                self._refresh()
        else:
            if self._cursors[self._q_idx] > 0:
                self._cursors[self._q_idx] -= 1
                self._refresh()

    def action_cursor_down(self) -> None:
        if self._on_submit:
            if self._submit_idx < 1:
                self._submit_idx += 1
                self._refresh()
        else:
            max_c = self._option_count(self._q_idx) - 1
            if self._cursors[self._q_idx] < max_c:
                self._cursors[self._q_idx] += 1
                self._refresh()

    def action_next_q(self) -> None:
        if self._on_submit or len(self._questions) <= 1:
            return
        if self._q_idx < len(self._questions) - 1:
            self._q_idx += 1
        else:
            self._on_submit = True
            self._submit_idx = 0
        self._refresh()

    def action_prev_q(self) -> None:
        if self._on_submit:
            self._on_submit = False
            self._q_idx = len(self._questions) - 1
            self._refresh()
        elif self._q_idx > 0:
            self._q_idx -= 1
            self._refresh()


    def action_toggle(self) -> None:
        if self._on_submit:
            return
        q = self._questions[self._q_idx]
        if not q.get("multiSelect", False):
            return
        cursor = self._cursors[self._q_idx]
        options = q.get("options", [])
        if cursor < len(options):
            self._selected[self._q_idx][cursor] = not self._selected[self._q_idx].get(cursor, False)
            self._refresh()

    def action_select(self) -> None:
        if self._on_submit:
            if self._submit_idx == 0:
                answers = {}
                for i, q in enumerate(self._questions):
                    key = q.get("question", q.get("message", f"q{i}"))
                    answers[key] = self._answered.get(i, "")
                self.post_message(self.Responded(answers))
            else:
                self.post_message(self.Responded(None))
        else:
            self._save_current_answer()
            if len(self._questions) == 1:
                answers = {}
                q = self._questions[0]
                key = q.get("question", q.get("message", "q0"))
                answers[key] = self._answered.get(0, "")
                self.post_message(self.Responded(answers))
            elif self._q_idx < len(self._questions) - 1:
                self._q_idx += 1
                self._refresh()
            else:
                self._on_submit = True
                self._submit_idx = 0
                self._refresh()


    def action_cancel(self) -> None:
        self.post_message(self.Responded(None))

    def on_key(self, event) -> None:
        if self._on_submit:
            return
        cursor = self._cursors[self._q_idx]
        options = self._questions[self._q_idx].get("options", [])
        if cursor != len(options):  # 当前光标不在 "Other" 上
            return
        key = event.key
        if key == "backspace":
            if self._others[self._q_idx]:
                self._others[self._q_idx] = self._others[self._q_idx][:-1]
                self._refresh()
            event.stop()
        elif len(key) == 1 and key.isprintable():
            self._others[self._q_idx] += key
            self._refresh()
            event.stop()
