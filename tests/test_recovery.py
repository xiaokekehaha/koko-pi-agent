# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import time

import pytest

from mewcode.context.manager import (
    RECOVERY_FILE_LIMIT,
    RECOVERY_SKILLS_BUDGET,
    RECOVERY_TOKENS_PER_FILE,
    RECOVERY_TOKENS_PER_SKILL,
    RecoveryState,
    _RECOVERY_CHARS_PER_TOKEN,
    build_recovery_attachment,
)

def test_recovery_attachment_empty_when_nothing_recorded():
    assert build_recovery_attachment(None, None) == ""
    assert build_recovery_attachment(RecoveryState(), None) == ""

def test_recovery_attachment_emits_all_sections():
    state = RecoveryState()
    state.record_file_read("/tmp/a.py", "print('hi')\n")
    state.record_skill_invocation("planner", "step 1\nstep 2\n")
    schemas = [
        {"name": "ReadFile", "description": "Read a file and return contents.\nWith line numbers."},
        {"name": "Bash", "description": ""},
    ]
    out = build_recovery_attachment(state, schemas)
    assert "/tmp/a.py" in out
    assert "planner" in out
    assert "- ReadFile — Read a file and return contents." in out
    assert "- Bash" in out
    assert "提示" in out  # 结尾提示部分的标题

def test_recovery_file_limit_and_order():
    state = RecoveryState()
    # 记录 7 个时间分散的文件；只有最新的 5 个应当出现。
    for i in range(7):
        state.record_file_read(f"/f{i}", "x")
        # 强制设置时间戳，使顺序确定
        rec = state._files[f"/f{i}"]
        rec.timestamp = 1000.0 + i

    files = state.snapshot_files(RECOVERY_FILE_LIMIT)
    assert len(files) == 5
    assert files[0].path == "/f6"  # 最新的排在最前
    assert files[-1].path == "/f2"

def test_recovery_truncates_per_file():
    huge = "x" * int(RECOVERY_TOKENS_PER_FILE * _RECOVERY_CHARS_PER_TOKEN * 3)
    state = RecoveryState()
    state.record_file_read("/big", huge)
    out = build_recovery_attachment(state, None)
    assert "内容已截断" in out

def test_recovery_skills_budget():
    state = RecoveryState()
    body = "y" * int(RECOVERY_TOKENS_PER_SKILL * _RECOVERY_CHARS_PER_TOKEN)
    for i in range(6):
        name = f"skill-{i}"
        state.record_skill_invocation(name, body)
        rec = state._skills[name]
        rec.timestamp = 1000.0 + i

    out = build_recovery_attachment(state, None)
    emitted = out.count("### skill-")
    # 25K / 每个 skill 5K ⇒ 最多 5 个
    assert 1 <= emitted <= 5
