# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


class PlanChoice(str, Enum):
    YOLO = "yolo"
    MANUAL = "manual"
    FEEDBACK = "feedback"


_OPTIONS = [
    ("Yes, enter YOLO mode (auto-approve all)", PlanChoice.YOLO),
    ("Yes, manually approve edits", PlanChoice.MANUAL),
    ("Tell MewCode what to change", PlanChoice.FEEDBACK),
]


class InlinePlanWidget(Vertical, can_focus=True):
    """内联的计划审批组件。"""

    BINDINGS = [
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "select", "Select", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("shift+tab", "approve_with_feedback", "Approve+Feedback", priority=True),
    ]

    class Responded(Message):


        def __init__(self, choice: PlanChoice, feedback: str = "") -> None:
            super().__init__()
            self.choice = choice
            self.feedback = feedback

    def __init__(self, **kwargs) -> None:
        super().__init__(id="plan-inline", **kwargs)
        self._cursor = 0
        self._input = ""


    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), id="plan-content")

    def on_mount(self) -> None:
        self.focus()

    def _build_content(self) -> str:
        lines = [
            "\n [bold #875fff]MewCode has written up a plan and is ready to execute. "
            "Would you like to proceed?[/bold #875fff]\n"
        ]
        for i, (label, _choice) in enumerate(_OPTIONS):
            if i == self._cursor:
                lines.append(f" [bold cyan]❯[/bold cyan] {i + 1}. [bold]{label}[/bold]")
            else:
                lines.append(f"   {i + 1}. [dim]{label}[/dim]")

        if self._cursor == 2:
            display = self._input if self._input else "[dim]Type feedback here...[/dim]"
            lines.append(f"      {display}█")
            lines.append("      [dim]shift+tab to approve with this feedback[/dim]")

        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#plan-content", Static).update(self._build_content())


    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._refresh()


    def action_cursor_down(self) -> None:
        if self._cursor < 2:
            self._cursor += 1
            self._refresh()

    def action_select(self) -> None:
        if self._cursor == 2 and self._input:
            self.post_message(self.Responded(PlanChoice.FEEDBACK, self._input))
        elif self._cursor == 0:
            self.post_message(self.Responded(PlanChoice.YOLO))
        elif self._cursor == 1:
            self.post_message(self.Responded(PlanChoice.MANUAL))

    def action_cancel(self) -> None:
        self.post_message(self.Responded(PlanChoice.MANUAL))

    def action_approve_with_feedback(self) -> None:
        if self._cursor == 2 and self._input:
            self.post_message(self.Responded(PlanChoice.FEEDBACK, self._input))


    def on_key(self, event) -> None:
        if self._cursor != 2:
            return
        key = event.key
        if key == "backspace":
            if self._input:
                self._input = self._input[:-1]
                self._refresh()
            event.stop()
        elif len(key) == 1 and key.isprintable():
            self._input += key
            self._refresh()
            event.stop()
