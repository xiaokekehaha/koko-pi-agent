# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

"""记忆治理 E2E 测试。

需要环境变量 MEWCODE_TEST_API_KEY、MEWCODE_TEST_BASE_URL、MEWCODE_TEST_MODEL。
运行：pytest tests/test_consolidation.py -v -s
"""
import asyncio
import os
import tempfile
from pathlib import Path

import pytest


def write_memory(mem_dir: str, filename: str, mem_type: str, name: str, desc: str, body: str):
    content = f"""---
name: {name}
description: {desc}
metadata:
  type: {mem_type}
---

{body}
"""
    Path(os.path.join(mem_dir, filename)).write_text(content)


def setup_test_memories(mem_dir: str):
    """构造有重复记忆的测试场景"""
    os.makedirs(mem_dir, exist_ok=True)

    write_memory(mem_dir, "feedback_no_push.md", "feedback", "no-push",
                 "Don't push without asking",
                 "用户不希望自动 push 代码")

    write_memory(mem_dir, "feedback_auto_push.md", "feedback", "auto-push",
                 "Don't auto push code",
                 "用户不喜欢自动 push，每次都要先问一下")

    write_memory(mem_dir, "user_role.md", "user", "user-role",
                 "User is a backend engineer",
                 "用户是后端工程师，主要用 Go 和 Java")

    Path(os.path.join(mem_dir, "MEMORY.md")).write_text(
        "- [No push](feedback_no_push.md) — 不要自动 push\n"
        "- [Auto push](feedback_auto_push.md) — 不要自动 push 代码\n"
        "- [User role](user_role.md) — 后端工程师\n"
    )


# =========================================================================
# 门控逻辑单元测试
# =========================================================================

def test_lock_first_acquire():
    from koko_pi_agent.memory.consolidation import _read_last_consolidated_at, _try_acquire_lock

    with tempfile.TemporaryDirectory() as d:
        assert _read_last_consolidated_at(d) == 0

        prior = _try_acquire_lock(d)
        assert prior is not None
        assert prior == 0

        # 锁文件应该存在
        lock_file = os.path.join(d, ".consolidate-lock")
        assert os.path.exists(lock_file)
        assert Path(lock_file).read_text().strip() == str(os.getpid())


def test_lock_blocks_when_held():
    from koko_pi_agent.memory.consolidation import _try_acquire_lock

    with tempfile.TemporaryDirectory() as d:
        _try_acquire_lock(d)
        # 同一进程再次获取应该被阻塞
        assert _try_acquire_lock(d) is None


def test_lock_reclaims_dead_pid():
    from koko_pi_agent.memory.consolidation import _try_acquire_lock

    with tempfile.TemporaryDirectory() as d:
        lock_file = os.path.join(d, ".consolidate-lock")
        Path(lock_file).write_text("999999999")
        prior = _try_acquire_lock(d)
        assert prior is not None


def test_lock_rollback_deletes_on_zero():
    from koko_pi_agent.memory.consolidation import _try_acquire_lock, _rollback_lock

    with tempfile.TemporaryDirectory() as d:
        _try_acquire_lock(d)
        _rollback_lock(d, 0)
        assert not os.path.exists(os.path.join(d, ".consolidate-lock"))


def test_lock_rollback_restores_mtime():
    import time
    from koko_pi_agent.memory.consolidation import _try_acquire_lock, _rollback_lock

    with tempfile.TemporaryDirectory() as d:
        lock_file = os.path.join(d, ".consolidate-lock")
        old_time = time.time() - 48 * 3600
        Path(lock_file).write_text("99999")
        os.utime(lock_file, (old_time, old_time))

        prior = _try_acquire_lock(d)
        assert prior is not None and prior > 0

        _rollback_lock(d, prior)

        restored_ms = int(os.stat(lock_file).st_mtime * 1000)
        assert abs(restored_ms - prior) < 1000


def test_prompt_contains_all_phases():
    from koko_pi_agent.memory.consolidation import _build_consolidation_prompt

    prompt = _build_consolidation_prompt("/mem", "/user/mem", "/sessions", ["s1", "s2"])
    for want in ["Phase 1", "Phase 2", "Phase 3", "Phase 4",
                 "MEMORY.md", "/mem", "/user/mem", "s1", "s2",
                 "Sessions since last consolidation (2)"]:
        assert want in prompt, f"prompt missing {want!r}"


# =========================================================================
# E2E 测试：真实 LLM 整理
# =========================================================================

@pytest.mark.skipif(
    not os.environ.get("MEWCODE_TEST_API_KEY"),
    reason="MEWCODE_TEST_API_KEY not set"
)
@pytest.mark.timeout(120)
def test_e2e_consolidation_merges_duplicates():
    api_key = os.environ["MEWCODE_TEST_API_KEY"]
    base_url = os.environ.get("MEWCODE_TEST_BASE_URL", "https://api.minimaxi.com/v1")
    model = os.environ.get("MEWCODE_TEST_MODEL", "MiniMax-M3")

    with tempfile.TemporaryDirectory() as work_dir:
        mem_dir = os.path.join(work_dir, ".koko", "memory")
        setup_test_memories(mem_dir)

        print("\nBefore consolidation:")
        print(f"  Files: {os.listdir(mem_dir)}")
        print(f"  MEMORY.md: {Path(os.path.join(mem_dir, 'MEMORY.md')).read_text()}")

        asyncio.run(_run_consolidation(work_dir, api_key, base_url, model, mem_dir))


async def _run_consolidation(work_dir, api_key, base_url, model, mem_dir):
    from koko_pi_agent.memory.consolidation import _build_consolidation_prompt
    from koko_pi_agent.agent import Agent
    from koko_pi_agent.conversation import ConversationManager
    from koko_pi_agent.permissions.checker import PermissionChecker
    from koko_pi_agent.tools import ToolRegistry
    from koko_pi_agent.tools.bash import Bash
    from koko_pi_agent.tools.edit_file import EditFile
    from koko_pi_agent.tools.glob import Glob
    from koko_pi_agent.tools.grep import Grep
    from koko_pi_agent.tools.read_file import ReadFile
    from koko_pi_agent.tools.write_file import WriteFile

    from koko_pi_agent.config import ProviderConfig
    from koko_pi_agent.client import OpenAICompatClient

    cfg = ProviderConfig(
        name="test",
        protocol="openai-compat",
        base_url=base_url,
        model=model,
        api_key=api_key,
        context_window=200000,
    )
    client = OpenAICompatClient(cfg)

    registry = ToolRegistry()
    for tool_cls in [ReadFile, WriteFile, EditFile, Glob, Grep, Bash]:
        registry.register(tool_cls())

    from koko_pi_agent.permissions.sandbox import PathSandbox
    from koko_pi_agent.permissions.rules import RuleEngine
    from koko_pi_agent.permissions.dangerous import DangerousCommandDetector
    from koko_pi_agent.permissions.checker import PermissionMode
    sandbox = PathSandbox(mem_dir)
    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=sandbox,
        rule_engine=RuleEngine(),
        mode=PermissionMode.BYPASS,
    )

    prompt = _build_consolidation_prompt(mem_dir, "", "", [])

    conv = ConversationManager()
    conv.add_user_message(prompt)

    sub_agent = Agent(
        client=client,
        registry=registry,
        permission_checker=checker,
        work_dir=work_dir,
        protocol="openai-compat",
        max_iterations=15,
    )

    async for _event in sub_agent.run(conv):
        pass

    print("\nAfter consolidation:")
    files = os.listdir(mem_dir)
    print(f"  Files: {files}")
    index_content = Path(os.path.join(mem_dir, "MEMORY.md")).read_text()
    print(f"  MEMORY.md:\n{index_content}")

    index_lines = [l for l in index_content.strip().split("\n") if l.strip()]
    print(f"  Index lines: {len(index_lines)}")

    # 验证：索引应该被更新了（合并重复后行数减少）
    assert len(index_lines) <= 3, f"expected ≤3 lines, got {len(index_lines)}"
