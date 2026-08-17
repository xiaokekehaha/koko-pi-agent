# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import re

MAX_SLUG_LENGTH = 64
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> str | None:
    if not name:
        return "name cannot be empty"
    if len(name) > MAX_SLUG_LENGTH:
        return f"name too long (max {MAX_SLUG_LENGTH} characters)"


    segments = name.split("/")
    for seg in segments:
        if not seg:
            return "name contains empty segment"
        if seg in (".", ".."):
            return "name must not contain '.' or '..' as a segment"
        if not _SEGMENT_RE.match(seg):
            return f"invalid segment: {seg!r} (allowed: letters, digits, '.', '-', '_')"


    return None


def flatten_slug(name: str) -> str:
    return name.replace("/", "+")
