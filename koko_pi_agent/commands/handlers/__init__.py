# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from koko_pi_agent.commands.handlers.clear import CLEAR_COMMAND
from koko_pi_agent.commands.handlers.compact import COMPACT_COMMAND
from koko_pi_agent.commands.handlers.help import HELP_COMMAND
from koko_pi_agent.commands.handlers.mcp import MCP_COMMAND
from koko_pi_agent.commands.handlers.memory import MEMORY_COMMAND
from koko_pi_agent.commands.handlers.mascot import MASCOT_COMMAND
from koko_pi_agent.commands.handlers.permission import PERMISSION_COMMAND
from koko_pi_agent.commands.handlers.plan import PLAN_COMMAND
from koko_pi_agent.commands.handlers.sandbox import SANDBOX_COMMAND
from koko_pi_agent.commands.handlers.session import SESSION_COMMAND
from koko_pi_agent.commands.handlers.skill import SKILL_COMMAND
from koko_pi_agent.commands.handlers.rewind import REWIND_COMMAND
from koko_pi_agent.commands.handlers.status import STATUS_COMMAND
from koko_pi_agent.commands.registry import CommandRegistry


ALL_COMMANDS = [
    HELP_COMMAND,
    COMPACT_COMMAND,
    CLEAR_COMMAND,
    PLAN_COMMAND,
    SESSION_COMMAND,
    MCP_COMMAND,
    MEMORY_COMMAND,
    MASCOT_COMMAND,
    PERMISSION_COMMAND,
    SANDBOX_COMMAND,
    REWIND_COMMAND,
    STATUS_COMMAND,
    SKILL_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)
