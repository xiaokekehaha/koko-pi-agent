from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Offset
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Button, Static


CORGI_FRAMES = (
    r"""
       /\     /\
      /  \___/  \
     /  o     o  \
    (      ^      )
     \   \___/   /
  ____/|       |\____  /
 /_____|_______|_____\
    |_|       |_|
""".strip("\n"),
    r"""
       /\     /\
      /  \___/  \
     /  -     -  \
    (      ^      )
     \    \_/    /
  ____/|       |\____ --
 /_____|_______|_____\
    |_|       |_|
""".strip("\n"),
    r"""
       /\     /\
      /  \___/  \
     /  o     o  \
    (      ^      )
     \   \_v_/   /
  ____/|       |\____  \
 /_____|_______|_____\
    |_|       |_|
""".strip("\n"),
)

# Backwards-compatible name for callers that only need the resting frame.
ASCII_MASCOT = CORGI_FRAMES[0]


class MascotText(Static):
    """Static text that doesn't start Textual's selection gesture."""

    ALLOW_SELECT = False


class MascotOverlay(Vertical, can_focus=True):
    """Draggable animated ASCII corgi shown by the ``/mascot`` command."""

    ALLOW_SELECT = False

    DEFAULT_CSS = """
    MascotOverlay {
        display: none;
        overlay: screen;
        constrain: inside;
        layer: mascot;
        dock: right;
        width: 36;
        max-width: 100%;
        height: 12;
        max-height: 100vh;
        margin: 4 2 0 0;
        padding: 0 1;
        background: $surface;
        border: round $primary;
        pointer: move;
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
        pointer: pointer;
    }

    #mascot-close:hover, #mascot-close:focus {
        color: $error;
        background: $surface-lighten-1;
    }

    #mascot-art {
        width: 100%;
        height: 8;
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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._frame_index = 0
        self._animation_timer: Timer | None = None
        self._drag_pointer: Offset | None = None
        self._drag_origin_offset = Offset(0, 0)
        self._drag_origin_region = Offset(0, 0)

    def compose(self) -> ComposeResult:
        with Horizontal(id="mascot-header"):
            yield MascotText("MewCode corgi", id="mascot-title")
            yield Button(
                "x",
                id="mascot-close",
                tooltip="Close mascot",
                compact=True,
                flat=True,
            )
        yield MascotText(CORGI_FRAMES[0], id="mascot-art", markup=False)
        yield MascotText("drag me  |  x / Esc to close", id="mascot-hint")

    def on_mount(self) -> None:
        self._animation_timer = self.set_interval(
            0.28,
            self._advance_frame,
            name="corgi-animation",
            pause=True,
        )

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def show_mascot(self, *, focus_close: bool = True) -> None:
        """Show the existing overlay without mounting a duplicate."""
        self.display = True
        if self._animation_timer is not None:
            self._animation_timer.resume()
        if focus_close:
            self.query_one("#mascot-close", Button).focus(scroll_visible=False)

    def close_mascot(self) -> None:
        if not self.display:
            return
        if self._animation_timer is not None:
            self._animation_timer.pause()
        self._finish_drag()
        self.display = False
        self.post_message(self.Closed())

    def _advance_frame(self) -> None:
        if not self.is_open:
            return
        self._frame_index = (self._frame_index + 1) % len(CORGI_FRAMES)
        self.query_one("#mascot-art", Static).update(
            CORGI_FRAMES[self._frame_index]
        )

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1 or event.screen_offset in self.query_one(
            "#mascot-close", Button
        ).region:
            return
        self._drag_pointer = Offset(
            int(event.screen_offset.x),
            int(event.screen_offset.y),
        )
        self._drag_origin_offset = self.offset
        self._drag_origin_region = self.region.offset
        self.capture_mouse()
        self.styles.pointer = "grabbing"
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_pointer is None:
            return

        pointer = Offset(int(event.screen_offset.x), int(event.screen_offset.y))
        delta = pointer - self._drag_pointer
        target = self._drag_origin_region + delta
        screen = self.screen.region
        max_x = max(screen.x, screen.right - self.region.width)
        max_y = max(screen.y, screen.bottom - self.region.height)
        target_x = min(max(target.x, screen.x), max_x)
        target_y = min(max(target.y, screen.y), max_y)
        clamped_delta = Offset(
            target_x - self._drag_origin_region.x,
            target_y - self._drag_origin_region.y,
        )
        new_offset = self._drag_origin_offset + clamped_delta
        if new_offset != self.offset:
            self.suppress_click()
        self.offset = (new_offset.x, new_offset.y)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_pointer is None:
            return
        self._finish_drag()
        event.stop()

    def on_mouse_release(self, _event: events.MouseRelease) -> None:
        """Clear drag state if capture is released by the app or terminal."""
        self._drag_pointer = None
        self.styles.pointer = "move"

    def _finish_drag(self) -> None:
        if self._drag_pointer is None:
            return
        self._drag_pointer = None
        self.release_mouse()
        self.styles.pointer = "move"

    def action_close(self) -> None:
        self.close_mascot()

    @on(Button.Pressed, "#mascot-close")
    def _close_from_button(self, event: Button.Pressed) -> None:
        event.stop()
        self.close_mascot()
