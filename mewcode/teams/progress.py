# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


SPINNER_VERBS = [
    "Accomplishing", "Architecting", "Baking", "Beboppin'", "Befuddling",
    "Bloviating", "Boogieing", "Boondoggling", "Bootstrapping", "Brewing",
    "Calculating", "Canoodling", "Caramelizing", "Cascading", "Cerebrating",
    "Choreographing", "Churning", "Coalescing", "Cogitating", "Combobulating",
    "Composing", "Computing", "Concocting", "Considering", "Contemplating",
    "Cooking", "Crafting", "Creating", "Crunching", "Crystallizing",
    "Cultivating", "Deciphering", "Deliberating", "Dilly-dallying",
    "Discombobulating", "Doodling", "Elucidating", "Enchanting", "Envisioning",
    "Fermenting", "Finagling", "Flambéing", "Flibbertigibbeting", "Flummoxing",
    "Forging", "Frolicking", "Gallivanting", "Garnishing", "Generating",
    "Germinating", "Grooving", "Harmonizing", "Hatching", "Honking",
    "Hullaballooing", "Ideating", "Imagining", "Improvising", "Incubating",
    "Inferring", "Infusing", "Kneading", "Lollygagging", "Manifesting",
    "Marinating", "Meandering", "Metamorphosing", "Mewing", "Moonwalking",
    "Moseying", "Mulling", "Musing", "Noodling", "Orbiting", "Orchestrating",
    "Percolating", "Philosophising", "Pondering", "Pontificating", "Pouncing",
    "Purring", "Puzzling", "Razzle-dazzling", "Ruminating", "Scampering",
    "Simmering", "Sketching", "Spelunking", "Spinning", "Sprouting",
    "Synthesizing", "Thinking", "Tinkering", "Transfiguring", "Transmuting",
    "Undulating", "Unfurling", "Unravelling", "Vibing", "Wandering",
    "Whisking", "Working", "Wrangling", "Zigzagging",
]


def random_verb() -> str:
    return random.choice(SPINNER_VERBS)


@dataclass
class ToolActivity:
    tool_name: str
    description: str

    @classmethod
    def from_tool_use(cls, tool_name: str, args: dict) -> ToolActivity:
        desc = _describe(tool_name, args)
        return cls(tool_name=tool_name, description=desc)


def _describe(tool_name: str, args: dict) -> str:
    match tool_name:
        case "ReadFile":
            return f"Reading {args.get('file_path', '')}"
        case "EditFile":
            return f"Editing {args.get('file_path', '')}"
        case "WriteFile":
            return f"Writing {args.get('file_path', '')}"
        case "Bash":
            cmd = str(args.get("command", ""))
            return f"Running {cmd[:40]}{'…' if len(cmd) > 40 else ''}"
        case "Glob":
            return f"Searching {args.get('pattern', '')}"
        case "Grep":
            return f"Grepping {args.get('pattern', '')}"
        case _:
            return tool_name


@dataclass
class TeammateProgress:
    name: str
    team_name: str
    status: str = "running"
    tool_use_count: int = 0
    token_count: int = 0
    last_activity: Optional[ToolActivity] = None
    recent_activities: list[ToolActivity] = field(default_factory=list)
    spinner_verb: str = field(default_factory=random_verb)
    start_time: float = field(default_factory=time.monotonic)
    last_message: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_tool_use(self, tool_name: str, args: dict) -> None:
        with self._lock:
            self.tool_use_count += 1
            act = ToolActivity.from_tool_use(tool_name, args)
            self.last_activity = act
            self.recent_activities.append(act)
            if len(self.recent_activities) > 5:
                self.recent_activities.pop(0)

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.token_count = input_tokens + output_tokens

    @property
    def activity_summary(self) -> str:
        with self._lock:
            if self.last_activity:
                return self.last_activity.description
            return self.spinner_verb

    @staticmethod
    def format_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)
