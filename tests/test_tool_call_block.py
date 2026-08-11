# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.app import ToolCallBlock, _format_detail


def test_format_detail_colors_edit_file_diff_lines():
    output = (
        "Updated foo.py with 1 addition and 1 removal\n"
        "   10  unchanged\n"
        "-   11  old line\n"
        "+   11  new line"
    )
    detail = _format_detail("EditFile", {"file_path": "foo.py"}, output)

    assert "[green]" in detail
    assert "new line" in detail
    assert "[red]" in detail
    assert "old line" in detail
    assert "[dim]" in detail


def test_format_detail_escapes_brackets_in_code():
    # Python 类型标注里的方括号不应该被当成 Rich markup 标签解析
    output = "+    1  def foo(x: list[int]) -> dict[str, int]:"
    detail = _format_detail("EditFile", {"file_path": "foo.py"}, output)
    assert "list\\[int]" in detail
    assert "dict\\[str, int]" in detail


def test_edit_file_block_auto_expands_on_success():
    block = ToolCallBlock("EditFile", {"file_path": "foo.py"})
    block.set_result("Updated foo.py with 1 addition and 0 removals\n+    1  hello", False, 0.1)

    assert block._collapsed is False
    assert "hello" in block.render().plain


def test_edit_file_block_stays_collapsed_on_error():
    block = ToolCallBlock("EditFile", {"file_path": "foo.py"})
    block.set_result("Error: old_string not found in file", True, 0.1)
    assert block._collapsed is True


def test_other_tools_still_default_collapsed():
    block = ToolCallBlock("Bash", {"command": "ls"})
    block.set_result("file1\nfile2", False, 0.1)
    assert block._collapsed is True
