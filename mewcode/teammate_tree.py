# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

from mewcode.teams.progress import TeammateProgress


class TeammateTree(Widget):
    """Renders a tree of teammate progress below the spinner."""

    DEFAULT_CSS = """
    TeammateTree {
        height: auto;
        margin: 0 1;
    }
    """

    teammates: reactive[list[TeammateProgress]] = reactive(list, layout=True)
    leader_tokens: reactive[int] = reactive(0)

    def render(self) -> Text:
        if not self.teammates:
            return Text("")

        lines = Text()
        # Leader line
        lines.append("  ┌─ ", style="dim")
        lines.append("team-lead", style="cyan")
        lines.append(": thinking…", style="dim")
        if self.leader_tokens > 0:
            lines.append(
                f" · {TeammateProgress.format_tokens(self.leader_tokens)} tokens",
                style="dim",
            )
        lines.append("\n")

        for i, p in enumerate(self.teammates):
            is_last = i == len(self.teammates) - 1
            connector = "  └─ " if is_last else "  ├─ "

            lines.append(connector, style="dim")
            lines.append(f"@{p.name}", style="cyan")
            lines.append(": ")

            if p.status == "completed":
                lines.append("completed", style="green")
            elif p.status == "failed":
                lines.append("failed", style="red")
            elif p.status == "idle":
                lines.append("idle", style="dim")
            else:
                lines.append(f"{p.activity_summary}…", style="dim")

            lines.append(
                f" · {p.tool_use_count} tools"
                f" · {TeammateProgress.format_tokens(p.token_count)} tokens",
                style="dim",
            )
            if not is_last:
                lines.append("\n")

        return lines
