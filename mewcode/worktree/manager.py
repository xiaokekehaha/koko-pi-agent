# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mewcode.worktree.changes import (
    CleanupResult,
    Changes,
    count_worktree_changes,
    has_worktree_changes,
)
from mewcode.worktree.models import Worktree, WorktreeSession
from mewcode.worktree.session import load_worktree_session, save_worktree_session
from mewcode.worktree.setup import perform_post_creation_setup
from mewcode.worktree.slug import flatten_slug, validate_slug

log = logging.getLogger(__name__)

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


class WorktreeError(Exception):
    pass


class WorktreeManager:
    def __init__(
        self,
        repo_root: str,
        symlink_directories: list[str] | None = None,
        worktree_dir: str | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.symlink_directories = symlink_directories or []
        self.worktree_dir = worktree_dir or str(
            Path(repo_root) / ".mewcode" / "worktrees"
        )
        self._mewcode_dir = Path(repo_root) / ".mewcode"
        self._lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self.current_session: WorktreeSession | None = None

    def _run_git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **GIT_ENV}
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    # ------------------------------------------------------------------
    # 快速恢复：直接从文件系统读取 HEAD SHA，无需启动 git 子进程
    # ------------------------------------------------------------------

    @staticmethod
    def read_worktree_head_sha(wt_path: str) -> str | None:
        wt = Path(wt_path)
        git_file = wt / ".git"
        if not git_file.exists():
            return None

        try:
            content = git_file.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir:"):
                return None
            gitdir = Path(content.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (wt / gitdir).resolve()

            commondir_file = gitdir / "commondir"
            if commondir_file.exists():
                commondir_rel = commondir_file.read_text(encoding="utf-8").strip()
                commondir = (gitdir / commondir_rel).resolve()
            else:
                commondir = gitdir

            head_file = gitdir / "HEAD"
            if not head_file.exists():
                return None
            head_content = head_file.read_text(encoding="utf-8").strip()

            if head_content.startswith("ref:"):
                ref_path = head_content.split(":", 1)[1].strip()
                ref_file = gitdir / ref_path
                if not ref_file.exists():
                    ref_file = commondir / ref_path
                if ref_file.exists():
                    return ref_file.read_text(encoding="utf-8").strip()
                packed_refs = commondir / "packed-refs"
                if packed_refs.exists():
                    for line in packed_refs.read_text(encoding="utf-8").splitlines():
                        if line.strip() and not line.startswith("#"):
                            parts = line.split()
                            if len(parts) == 2 and parts[1] == ref_path:
                                return parts[0]
                return None
            return head_content
        except OSError:
            return None

    # ------------------------------------------------------------------
    # 创建 worktree
    # ------------------------------------------------------------------

    async def create(self, name: str, base_branch: str = "HEAD") -> Worktree:
        async with self._lock:
            err = validate_slug(name)
            if err:
                raise WorktreeError(err)

            if name in self.active:
                raise WorktreeError(f"worktree already exists: {name}")

            flat_slug = flatten_slug(name)
            wt_path = os.path.join(self.worktree_dir, flat_slug)
            branch_name = f"worktree-{flat_slug}"

            head_sha = self.read_worktree_head_sha(wt_path)
            if head_sha is not None:
                log.info("Fast recovery: reusing existing worktree at %s", wt_path)
                wt = Worktree(
                    name=name,
                    path=wt_path,
                    branch=branch_name,
                    based_on=base_branch,
                    head_commit=head_sha,
                )
                self.active[name] = wt
                return wt

            os.makedirs(self.worktree_dir, exist_ok=True)

            result = self._run_git([
                "worktree", "add",
                "-B", branch_name, wt_path, base_branch,
            ])
            if result.returncode != 0:
                raise WorktreeError(
                    f"git worktree add failed: {result.stderr.strip()}"
                )

            perform_post_creation_setup(
                self.repo_root,
                wt_path,
                symlink_directories=self.symlink_directories,
            )

            head_sha = self.read_worktree_head_sha(wt_path) or ""
            wt = Worktree(
                name=name,
                path=wt_path,
                branch=branch_name,
                based_on=base_branch,
                head_commit=head_sha,
            )
            self.active[name] = wt
            return wt

    # ------------------------------------------------------------------
    # 进入 worktree
    # ------------------------------------------------------------------

    async def enter(self, name: str) -> WorktreeSession:
        wt = self.active.get(name)
        if wt is None:
            raise WorktreeError(f"worktree not found: {name}")

        original_cwd = os.getcwd()
        original_branch = self._get_current_branch()
        original_head = self._get_head_commit()

        session = WorktreeSession(
            original_cwd=original_cwd,
            worktree_path=wt.path,
            worktree_name=name,
            original_branch=original_branch,
            original_head_commit=original_head,
        )
        self.current_session = session
        save_worktree_session(self._mewcode_dir, session)
        return session

    # ------------------------------------------------------------------
    # 退出 worktree
    # ------------------------------------------------------------------


    async def exit(
        self,
        name: str,
        action: str = "keep",
        discard_changes: bool = False,
    ) -> None:
        wt = self.active.get(name)
        if wt is None:
            raise WorktreeError(f"worktree not found: {name}")

        if action == "remove" and not discard_changes:
            changes = count_worktree_changes(wt.path, wt.head_commit)
            if changes.uncommitted > 0 or changes.new_commits > 0:
                raise WorktreeError(
                    f"worktree has changes ({changes.uncommitted} uncommitted, "
                    f"{changes.new_commits} new commits). "
                    "Set discard_changes=True to force removal."
                )

        self.current_session = None
        save_worktree_session(self._mewcode_dir, None)

        if action == "remove":
            await self._remove_worktree(name, wt)

    # ------------------------------------------------------------------
    # 删除 worktree（内部方法）
    # ------------------------------------------------------------------

    async def _remove_worktree(self, name: str, wt: Worktree) -> None:
        result = self._run_git(["worktree", "remove", "--force", wt.path])
        if result.returncode != 0:
            log.warning("git worktree remove failed: %s", result.stderr.strip())

        await asyncio.sleep(0.1)

        flat_slug = flatten_slug(name)
        branch_name = f"worktree-{flat_slug}"
        self._run_git(["branch", "-D", branch_name])

        self.active.pop(name, None)

    # ------------------------------------------------------------------
    # 自动清理
    # ------------------------------------------------------------------


    async def auto_cleanup(self, name: str, head_commit: str) -> CleanupResult:
        wt = self.active.get(name)
        if wt is None:
            return CleanupResult(kept=False)

        if has_worktree_changes(wt.path, head_commit):
            return CleanupResult(kept=True, path=wt.path, branch=wt.branch)

        await self._remove_worktree(name, wt)
        return CleanupResult(kept=False)

    # ------------------------------------------------------------------
    # 列出 / 查询
    # ------------------------------------------------------------------

    def list_worktrees(self) -> list[Worktree]:
        return list(self.active.values())


    def get_current_session(self) -> WorktreeSession | None:
        return self.current_session

    # ------------------------------------------------------------------
    # 从持久化的 session 中恢复
    # ------------------------------------------------------------------

    def restore_session(self) -> WorktreeSession | None:
        session = load_worktree_session(self._mewcode_dir)
        if session is None:
            return None
        wt_path = session.worktree_path
        head_sha = self.read_worktree_head_sha(wt_path)
        if head_sha is None:
            save_worktree_session(self._mewcode_dir, None)
            return None

        wt = Worktree(
            name=session.worktree_name,
            path=wt_path,
            branch=f"worktree-{flatten_slug(session.worktree_name)}",
            based_on="unknown",
            head_commit=head_sha,
        )
        self.active[session.worktree_name] = wt
        self.current_session = session
        return session

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------


    def _get_current_branch(self) -> str:
        try:
            result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            return result.stdout.strip() if result.returncode == 0 else "HEAD"
        except (subprocess.SubprocessError, OSError):
            return "HEAD"

    def _get_head_commit(self) -> str:
        try:
            result = self._run_git(["rev-parse", "HEAD"])
            return result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.SubprocessError, OSError):
            return ""
