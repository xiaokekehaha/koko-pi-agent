# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""Git Worktree 管理系统的测试（第 13 章）。"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from koko_pi_agent.config import WorktreeConfig, load_config
from koko_pi_agent.worktree.changes import count_worktree_changes, has_worktree_changes
from koko_pi_agent.worktree.integration import build_worktree_notice, generate_worktree_name
from koko_pi_agent.worktree.manager import WorktreeError, WorktreeManager
from koko_pi_agent.worktree.models import WorktreeSession
from koko_pi_agent.worktree.session import load_worktree_session, save_worktree_session
from koko_pi_agent.worktree.slug import flatten_slug, validate_slug

# =========================================================================
# A. Slug 校验
# =========================================================================

class TestValidateSlug:
    def test_valid_simple(self):
        assert validate_slug("my-feature") is None

    def test_valid_with_dots(self):
        assert validate_slug("v1.0") is None

    def test_valid_nested(self):
        assert validate_slug("team/alice") is None

    def test_valid_single_char(self):
        assert validate_slug("a") is None

    def test_valid_underscores(self):
        assert validate_slug("my_feature_2") is None

    def test_empty(self):
        assert validate_slug("") is not None

    def test_too_long(self):
        assert validate_slug("a" * 65) is not None
        assert validate_slug("a" * 64) is None

    def test_path_traversal(self):
        assert validate_slug("../../etc/passwd") is not None

    def test_dot_segment(self):
        assert validate_slug("foo/./bar") is not None
        assert validate_slug("foo/../bar") is not None

    def test_dot_only(self):
        assert validate_slug(".") is not None
        assert validate_slug("..") is not None

    def test_spaces(self):
        assert validate_slug("my feature") is not None

    def test_special_chars(self):
        assert validate_slug("my@feature") is not None
        assert validate_slug("my feature") is not None
        assert validate_slug("my;feature") is not None

    def test_empty_segment(self):
        assert validate_slug("foo//bar") is not None

class TestFlattenSlug:
    def test_no_slash(self):
        assert flatten_slug("my-feature") == "my-feature"

    def test_with_slash(self):
        assert flatten_slug("team/alice") == "team+alice"

    def test_multiple_slashes(self):
        assert flatten_slug("a/b/c") == "a+b+c"

# =========================================================================
# B. 配置扩展
# =========================================================================

class TestWorktreeConfig:
    def test_defaults(self):
        cfg = WorktreeConfig()
        assert "node_modules" in cfg.symlink_directories
        assert cfg.stale_cleanup_interval == 3600
        assert cfg.stale_cutoff_hours == 24

    def test_load_config_without_worktree_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: openai\n"
            "    base_url: http://localhost\n"
            "    model: gpt-4\n"
        )
        cfg = load_config(config_file)
        assert cfg.worktree.stale_cleanup_interval == 3600

    def test_load_config_with_worktree_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: openai\n"
            "    base_url: http://localhost\n"
            "    model: gpt-4\n"
            "worktree:\n"
            "  symlink_directories:\n"
            "    - .venv\n"
            "  stale_cleanup_interval: 1800\n"
            "  stale_cutoff_hours: 12\n"
        )
        cfg = load_config(config_file)
        assert cfg.worktree.symlink_directories == [".venv"]
        assert cfg.worktree.stale_cleanup_interval == 1800
        assert cfg.worktree.stale_cutoff_hours == 12

# =========================================================================
# H. 会话持久化
# =========================================================================

class TestSessionPersistence:

    def test_save_and_load(self, tmp_path):
        session = WorktreeSession(
            original_cwd="/original",
            worktree_path="/wt/path",
            worktree_name="my-feature",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(tmp_path, session)
        loaded = load_worktree_session(tmp_path)
        assert loaded is not None
        assert loaded.worktree_name == "my-feature"
        assert loaded.original_cwd == "/original"

    def test_save_none_clears(self, tmp_path):
        session = WorktreeSession(
            original_cwd="/original",
            worktree_path="/wt/path",
            worktree_name="my-feature",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(tmp_path, session)
        save_worktree_session(tmp_path, None)
        loaded = load_worktree_session(tmp_path)
        assert loaded is None

    def test_load_missing_file(self, tmp_path):
        assert load_worktree_session(tmp_path) is None

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "worktree_session.json"
        path.write_text("not json")
        assert load_worktree_session(tmp_path) is None

# =========================================================================
# 集成辅助函数
# =========================================================================

class TestIntegrationHelpers:
    def test_generate_worktree_name(self):
        name = generate_worktree_name()
        # "agent-a"(7字符) + token_hex(4)[:7](7位十六进制) = 14 字符
        assert name.startswith("agent-a")
        assert len(name) == 14

    def test_build_worktree_notice(self):
        notice = build_worktree_notice("/parent/dir", "/wt/dir")
        assert "/parent/dir" in notice
        assert "/wt/dir" in notice
        assert "WORKTREE CONTEXT" in notice

# =========================================================================
# D. WorktreeManager（需要真实的 git 仓库）
# =========================================================================

def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)
    (path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True)

@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo

@pytest.fixture
def manager(git_repo):
    return WorktreeManager(
        repo_root=str(git_repo),
        symlink_directories=[],
    )

class TestWorktreeManager:
    @pytest.mark.asyncio
    async def test_create(self, manager, git_repo):
        wt = await manager.create("test-feature")
        assert wt.name == "test-feature"
        assert wt.branch == "worktree-test-feature"
        assert Path(wt.path).exists()
        assert (Path(wt.path) / "README.md").exists()

    @pytest.mark.asyncio
    async def test_create_invalid_slug(self, manager):
        with pytest.raises(WorktreeError, match="must not contain"):
            await manager.create("../escape")

    @pytest.mark.asyncio
    async def test_create_duplicate(self, manager):
        await manager.create("dup")
        with pytest.raises(WorktreeError, match="already exists"):
            await manager.create("dup")

    @pytest.mark.asyncio
    async def test_create_nested_slug(self, manager):
        wt = await manager.create("team/alice")
        assert wt.branch == "worktree-team+alice"
        assert Path(wt.path).exists()

    @pytest.mark.asyncio
    async def test_fast_recovery(self, manager):
        wt1 = await manager.create("recover")
        path = wt1.path
        manager.active.clear()
        wt2 = await manager.create("recover")
        assert wt2.path == path
        assert wt2.head_commit == wt1.head_commit

    @pytest.mark.asyncio
    async def test_enter_and_session(self, manager):
        await manager.create("enter-test")
        session = await manager.enter("enter-test")
        assert session.worktree_name == "enter-test"
        assert manager.current_session is not None

    @pytest.mark.asyncio
    async def test_enter_sets_session(self, manager):
        await manager.create("session-test")
        await manager.enter("session-test")
        assert manager.current_session is not None
        assert manager.current_session.worktree_name == "session-test"

    @pytest.mark.asyncio
    async def test_exit_keep(self, manager):
        await manager.create("exit-keep")
        await manager.enter("exit-keep")
        await manager.exit("exit-keep", action="keep")
        assert manager.current_session is None
        assert "exit-keep" in manager.active

    @pytest.mark.asyncio
    async def test_exit_remove_clean(self, manager):
        wt = await manager.create("exit-rm")
        await manager.enter("exit-rm")
        await manager.exit("exit-rm", action="remove", discard_changes=True)
        assert "exit-rm" not in manager.active

    @pytest.mark.asyncio
    async def test_exit_remove_with_changes_blocked(self, manager, git_repo):
        wt = await manager.create("exit-protect")
        (Path(wt.path) / "new_file.txt").write_text("changes")
        await manager.enter("exit-protect")
        with pytest.raises(WorktreeError, match="has changes"):
            await manager.exit("exit-protect", action="remove", discard_changes=False)

    @pytest.mark.asyncio
    async def test_list_worktrees(self, manager):
        await manager.create("list-a")
        await manager.create("list-b")
        wts = manager.list_worktrees()
        names = {wt.name for wt in wts}
        assert names == {"list-a", "list-b"}

    @pytest.mark.asyncio
    async def test_enter_nonexistent(self, manager):
        with pytest.raises(WorktreeError, match="not found"):
            await manager.enter("nope")

# =========================================================================
# F. 变更检测与自动清理
# =========================================================================

class TestChangeDetection:
    @pytest.mark.asyncio
    async def test_clean_worktree(self, manager):
        wt = await manager.create("clean-wt")
        assert not has_worktree_changes(wt.path, wt.head_commit)

    @pytest.mark.asyncio
    async def test_uncommitted_changes(self, manager):
        wt = await manager.create("dirty-wt")
        (Path(wt.path) / "dirty.txt").write_text("new")
        assert has_worktree_changes(wt.path, wt.head_commit)

    @pytest.mark.asyncio
    async def test_new_commits(self, manager):
        wt = await manager.create("commit-wt")
        assert wt.head_commit, "head_commit should not be empty after create"
        (Path(wt.path) / "committed.txt").write_text("new")
        subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
        result = subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=t@t",
             "commit", "-m", "test"],
            cwd=wt.path, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"commit failed: {result.stderr}"
        changes = count_worktree_changes(wt.path, wt.head_commit)
        assert changes.new_commits > 0

    @pytest.mark.asyncio
    async def test_auto_cleanup_removes_clean(self, manager):
        wt = await manager.create("auto-clean")
        result = await manager.auto_cleanup("auto-clean", wt.head_commit)
        assert not result.kept
        assert "auto-clean" not in manager.active

    @pytest.mark.asyncio
    async def test_auto_cleanup_keeps_dirty(self, manager):
        wt = await manager.create("auto-dirty")
        (Path(wt.path) / "file.txt").write_text("content")
        result = await manager.auto_cleanup("auto-dirty", wt.head_commit)
        assert result.kept
        assert result.path == wt.path
        assert "auto-dirty" in manager.active

# =========================================================================
# D4. read_worktree_head_sha
# =========================================================================

class TestReadWorktreeHeadSha:
    @pytest.mark.asyncio
    async def test_valid_worktree(self, manager):
        wt = await manager.create("sha-test")
        sha = WorktreeManager.read_worktree_head_sha(wt.path)
        assert sha is not None
        assert len(sha) == 40

    def test_nonexistent_dir(self):
        sha = WorktreeManager.read_worktree_head_sha("/nonexistent/path")
        assert sha is None

    def test_not_a_worktree(self, tmp_path):
        sha = WorktreeManager.read_worktree_head_sha(str(tmp_path))
        assert sha is None
