from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static


ASCII_MASCOT = r"""
       /\_/\
      ( o.o )
       > ^ <
     .-------.
    / MewCode \
    '---------'
""".strip("\n")


class MascotOverlay(Vertical, can_focus=True):
    """Non-modal floating ASCII mascot shown by the ``/mascot`` command."""

    DEFAULT_CSS = """
    MascotOverlay {
        display: none;
        overlay: screen;
        layer: mascot;
        dock: right;
        width: 36;
        max-width: 100%;
        height: 12;
        margin: 4 2 0 0;
        padding: 0 1;
        background: $surface;
        border: round $primary;
    }

    #mascot-header {
        width: 100%;
        height: 1;
    }

    #mascot-title {
        width: 1fr;
        height: 1;
        color: $primary;
        text-style: bold;
    }

    #mascot-close {
        width: 3;
        min-width: 3;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
        color: $text-muted;
        text-style: bold;
        content-align: center middle;
    }

    #mascot-close:hover, #mascot-close:focus {
        color: $error;
        background: $surface-lighten-1;
    }

    #mascot-art {
        width: 100%;
        height: 7;
        color: $text;
        content-align: center middle;
        text-align: center;
    }

    #mascot-hint {
        width: 100%;
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close mascot", priority=True, show=False),
    ]

    class Closed(Message):
        """Posted after the mascot is closed by mouse or keyboard."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="mascot-header"):
            yield Static("MewCode buddy", id="mascot-title")
            yield Button(
                "x",
                id="mascot-close",
                tooltip="Close mascot",
                compact=True,
                flat=True,
            )
        yield Static(ASCII_MASCOT, id="mascot-art", markup=False)
        yield Static("/mascot  |  Esc to close", id="mascot-hint")

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def show_mascot(self) -> None:
        """Show the existing overlay without mounting a duplicate."""
        self.display = True
        self.query_one("#mascot-close", Button).focus(scroll_visible=False)

    def close_mascot(self) -> None:
        if not self.display:
            return
        self.display = False
        self.post_message(self.Closed())

    def action_close(self) -> None:
        self.close_mascot()

    @on(Button.Pressed, "#mascot-close")
    def _close_from_button(self, event: Button.Pressed) -> None:
        event.stop()
        self.close_mascot()
