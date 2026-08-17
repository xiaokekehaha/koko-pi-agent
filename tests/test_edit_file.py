# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from pathlib import Path

import pytest

from koko_pi_agent.tools.edit_file import EditFile, Params


@pytest.mark.asyncio
async def test_successful_edit_returns_colorable_diff(tmp_path: Path):
    file = tmp_path / "utils.py"
    file.write_text("def format_date(d):\n    return str(d)\n", encoding="utf-8")

    tool = EditFile()
    result = await tool.execute(Params(
        file_path=str(file),
        old_string="def format_date(d):",
        new_string="def format_date(d, tz=None):",
    ))

    assert not result.is_error
    assert result.output.startswith("Updated")
    assert "1 addition" in result.output
    assert "1 removal" in result.output
    assert "+" in result.output
    assert "-" in result.output

    # 确认文件确实被改写
    assert "tz=None" in file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_nonexistent_file_is_error():
    tool = EditFile()
    result = await tool.execute(Params(
        file_path="/nonexistent/path.txt",
        old_string="a",
        new_string="b",
    ))
    assert result.is_error
