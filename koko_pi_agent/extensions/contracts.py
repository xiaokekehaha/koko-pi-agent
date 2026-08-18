from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from koko_pi_agent.tools import ToolRegistry

if TYPE_CHECKING:
    from koko_pi_agent.extensions.host import ExtensionAPI


class RuntimeProfile(str, Enum):
    TUI_LEAD = "tui_lead"
    PROMPT_LEAD = "prompt_lead"
    REMOTE_LEAD = "remote_lead"
    TEAMMATE_WORKER = "teammate_worker"


# profile 不再只挑选 Tool：它同样决定资源与后台任务类 extension 是否激活。
# 保留旧名作为兼容别名，入口逐步改用 RuntimeProfile。
ToolProfile = RuntimeProfile


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
    kind: str = "extension"
    name: str = ""
    phase: str = ""


@dataclass(frozen=True)
class ExtensionCleanupFailure:
    extension_id: str
    source: str
    kind: str
    name: str
    error: BaseException

    def describe(self) -> str:
        return f"{self.kind} '{self.name}' of {self.extension_id}: {self.error}"


class ExtensionTaskHandle:
    """只读句柄。扩展通过它观察自己启动的后台任务，但拿不到原始 Task。"""

    def __init__(
        self,
        *,
        extension_id: str,
        name: str,
        task: asyncio.Task[None],
    ) -> None:
        self._extension_id = extension_id
        self._name = name
        self._task = task

    @property
    def extension_id(self) -> str:
        return self._extension_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def done(self) -> bool:
        return self._task.done()

    @property
    def status(self) -> str:
        if not self._task.done():
            return "running"
        if self._task.cancelled():
            return "cancelled"
        return "failed" if self._task.exception() is not None else "completed"


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


class ExtensionCloseError(RuntimeError):
    """关闭期间的清理失败聚合。抛出它时 Session 与 Runtime 都已经是 closed。"""

    def __init__(self, failures: tuple[ExtensionCleanupFailure, ...]) -> None:
        self.failures = failures
        detail = "; ".join(failure.describe() for failure in failures)
        super().__init__(f"{len(failures)} extension cleanup failure(s): {detail}")
