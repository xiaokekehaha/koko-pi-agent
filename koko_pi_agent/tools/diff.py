# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from dataclasses import dataclass

_CONTEXT_LINES = 3
# 防止超大文件产出天量 diff 文本拖垮 TUI 渲染和上下文占用
_MAX_DIFF_LINES = 200


@dataclass
class DiffResult:
    text: str
    additions: int
    removals: int


def build_diff(old_content: str, new_content: str) -> DiffResult:
    """对比编辑前后的文件内容，生成一段带行号的 diff。

    利用"编辑只改动中间一小段"的特点，从两端找公共前缀/后缀行，
    避免跑通用的 LCS/Myers diff 算法（对大文件更快，实现也更简单）。
    输出格式固定，便于终端渲染和测试断言。
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    prefix_len = 0
    max_prefix = min(len(old_lines), len(new_lines))
    while prefix_len < max_prefix and old_lines[prefix_len] == new_lines[prefix_len]:
        prefix_len += 1

    suffix_len = 0
    max_suffix = max_prefix - prefix_len
    while (
        suffix_len < max_suffix
        and old_lines[len(old_lines) - 1 - suffix_len] == new_lines[len(new_lines) - 1 - suffix_len]
    ):
        suffix_len += 1

    removed_lines = old_lines[prefix_len : len(old_lines) - suffix_len]
    added_lines = new_lines[prefix_len : len(new_lines) - suffix_len]

    context_start = max(0, prefix_len - _CONTEXT_LINES)
    context_before = old_lines[context_start:prefix_len]
    context_end = min(len(old_lines), len(old_lines) - suffix_len + _CONTEXT_LINES)
    context_after = old_lines[len(old_lines) - suffix_len : context_end]

    out: list[str] = []
    old_line_no = context_start + 1
    new_line_no = context_start + 1
    truncated = False

    def push(prefix: str, line_no: int, content: str) -> None:
        nonlocal truncated
        if len(out) >= _MAX_DIFF_LINES:
            truncated = True
            return
        out.append(f"{prefix} {line_no:>4}  {content}")

    for line in context_before:
        push(" ", old_line_no, line)
        old_line_no += 1
        new_line_no += 1
    for line in removed_lines:
        push("-", old_line_no, line)
        old_line_no += 1
    for line in added_lines:
        push("+", new_line_no, line)
        new_line_no += 1
    for line in context_after:
        push(" ", old_line_no, line)
        old_line_no += 1
        new_line_no += 1

    if truncated:
        out.append(f"  … (diff truncated at {_MAX_DIFF_LINES} lines)")

    return DiffResult(text="\n".join(out), additions=len(added_lines), removals=len(removed_lines))
