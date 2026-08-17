# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent

from __future__ import annotations

from koko_pi_agent.tools.diff import build_diff


def test_single_line_change():
    old = "a\nb\nc\nd\ne\n"
    new = "a\nb\nX\nd\ne\n"
    d = build_diff(old, new)

    assert d.additions == 1
    assert d.removals == 1
    assert "-    3  c" in d.text
    assert "+    3  X" in d.text
    assert "   2  b" in d.text
    assert "   4  d" in d.text


def test_pure_insertion():
    d = build_diff("a\nb\n", "a\nX\nY\nb\n")
    assert d.removals == 0
    assert d.additions == 2
    assert "+    2  X" in d.text
    assert "+    3  Y" in d.text


def test_pure_deletion():
    d = build_diff("a\nb\nc\n", "a\nc\n")
    assert d.additions == 0
    assert d.removals == 1
    assert "-    2  b" in d.text


def test_trims_unrelated_prefix_suffix():
    old_lines = [f"line{i}" for i in range(20)]
    new_lines = list(old_lines)
    new_lines[10] = "CHANGED"

    d = build_diff("\n".join(old_lines), "\n".join(new_lines))
    assert "line0\n" not in d.text
    assert "-   11  line10" in d.text
    assert "+   11  CHANGED" in d.text


def test_caps_very_large_diff():
    old_lines = [f"old{i}" for i in range(500)]
    new_lines = [f"new{i}" for i in range(500)]
    d = build_diff("\n".join(old_lines), "\n".join(new_lines))
    assert "truncated" in d.text
    assert len(d.text.split("\n")) < 500
