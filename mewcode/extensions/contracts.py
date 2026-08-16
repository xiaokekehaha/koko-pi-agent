from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from mewcode.tools import ToolRegistry

if TYPE_CHECKING:
    from mewcode.extensions.host import ExtensionAPI


class ToolProfile(str, Enum):
    TUI_LEAD = "tui_lead"
    PROMPT_LEAD = "prompt_lead"
    REMOTE_LEAD = "remote_lead"
    TEAMMATE_WORKER = "teammate_worker"


ExtensionInstaller = Callable[["ExtensionAPI", Any], Awaitable[None] | None]


@dataclass(frozen=True)
class ExtensionDefinition:
    extension_id: str
    display_name: str
    source: str
    installer: ExtensionInstaller
    critical: bool = True
    profiles: frozenset[ToolProfile] | None = None


@dataclass(frozen=True)
class SessionContext:
    runtime_id: str
    generation: int
    work_dir: str
    profile: ToolProfile


@dataclass(frozen=True)
class OpenExtensionSession:
    context: SessionContext
    registry: ToolRegistry
    bindings: Any


@dataclass(frozen=True)
class ExtensionDiagnostic:
    extension_id: str
    source: str
    status: str
    error: str = ""


class DuplicateExtensionIdError(ValueError):
    pass


class ExtensionPhaseError(RuntimeError):
    pass


class ExtensionStartupError(RuntimeError):
    def __init__(
        self,
        extension_id: str,
        cause: BaseException,
        diagnostics: tuple[ExtensionDiagnostic, ...],
    ) -> None:
        self.extension_id = extension_id
        self.cause = cause
        self.diagnostics = diagnostics
        super().__init__(f"Extension '{extension_id}' failed to start: {cause}")
