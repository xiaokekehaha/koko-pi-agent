# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, quote

import httpx

log = logging.getLogger(__name__)

# --- 安全限制：防止恶意 / 错误 URL 拉取过多数据 ---
MAX_FILE_SIZE = 1 << 20       # 单文件 1 MiB
MAX_TOTAL_SIZE = 8 << 20      # 整个 skill 8 MiB
MAX_FILE_COUNT = 64
MAX_RECURSION_DEPTH = 4
HTTP_TIMEOUT = 30.0

# skill 名称只允许小写字母、数字、连字符、下划线
_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")

GITHUB_API_BASE = "https://api.github.com"


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

@dataclass
class SkillSource:
    """解析后的 skill 来源信息，最终统一走 GitHub Contents API 拉取。"""
    owner: str
    repo: str
    ref: str            # 分支或 tag，默认 "main"
    subpath: str        # 仓库内 skill 目录的路径（无尾 /）
    name: str           # skill 名称（subpath 最后一段）
    original: str       # 用户原始 URL


@dataclass
class InstallReport:
    """安装完成后的汇报信息。"""
    skill_name: str = ""
    target_dir: str = ""
    file_count: int = 0
    total_bytes: int = 0


# ------------------------------------------------------------------
# URL 解析：支持三种格式
# ------------------------------------------------------------------

def parse_skill_url(raw: str) -> SkillSource:
    """将用户提供的 URL 解析为 SkillSource。

    支持三种 URL 格式：
    1. skills.sh:  https://www.skills.sh/<owner>/<repo>/<skill-name>
    2. github.com: https://github.com/<owner>/<repo>/tree/<ref>/<subpath>
    3. raw.githubusercontent.com: https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<subpath>/SKILL.md
    """
    raw = raw.strip()
    u = urlparse(raw)
    if u.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are supported")

    parts = [p for p in u.path.strip("/").split("/") if p]

    host = u.hostname or ""

    # skills.sh 格式
    if host in ("www.skills.sh", "skills.sh"):
        if len(parts) < 3:
            raise ValueError("skills.sh URL must be /<owner>/<repo>/<skill-name>")
        return SkillSource(
            owner=parts[0],
            repo=parts[1],
            ref="main",
            subpath="skills/" + "/".join(parts[2:]),
            name=parts[-1],
            original=raw,
        )

    # github.com 格式
    if host == "github.com":
        # /<owner>/<repo>/tree/<ref>/<...subpath>
        if len(parts) < 5 or parts[2] != "tree":
            raise ValueError("github.com URL must be /<owner>/<repo>/tree/<ref>/<subpath>")
        sub = "/".join(parts[4:])
        return SkillSource(
            owner=parts[0],
            repo=parts[1],
            ref=parts[3],
            subpath=sub,
            name=parts[-1],
            original=raw,
        )

    # raw.githubusercontent.com 格式
    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise ValueError("raw.githubusercontent.com URL too short")
        # 去掉尾部文件名，保留 skill 目录路径
        sub_parts = parts[3:]
        if sub_parts and "." in sub_parts[-1]:
            sub_parts = sub_parts[:-1]
        if not sub_parts:
            raise ValueError("raw URL missing skill subpath")
        return SkillSource(
            owner=parts[0],
            repo=parts[1],
            ref=parts[2],
            subpath="/".join(sub_parts),
            name=sub_parts[-1],
            original=raw,
        )

    raise ValueError(f"unsupported host {host!r} (try skills.sh or github.com)")


# ------------------------------------------------------------------
# GitHub Contents API 拉取
# ------------------------------------------------------------------

@dataclass
class _ContentEntry:
    """GitHub Contents API 返回的单条条目。"""
    name: str
    path: str
    type: str          # "file" | "dir" | "symlink" | "submodule"
    download_url: str | None = None
    content: str | None = None
    encoding: str | None = None
    size: int = 0


def _parse_entries(data: list | dict) -> list[_ContentEntry]:
    """把 API 返回的 JSON 解析为 _ContentEntry 列表。"""
    items = data if isinstance(data, list) else [data]
    return [
        _ContentEntry(
            name=e.get("name", ""),
            path=e.get("path", ""),
            type=e.get("type", ""),
            download_url=e.get("download_url"),
            content=e.get("content"),
            encoding=e.get("encoding"),
            size=e.get("size", 0),
        )
        for e in items
    ]


async def _list_contents(
    client: httpx.AsyncClient, src: SkillSource, subpath: str
) -> list[_ContentEntry]:
    """调用 GitHub Contents API 列出指定路径下的文件。"""
    url = (
        f"{GITHUB_API_BASE}/repos/{src.owner}/{src.repo}"
        f"/contents/{subpath}?ref={quote(src.ref, safe='')}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mewcode-install-skill",
    }
    resp = await client.get(url, headers=headers)
    if resp.status_code == 403:
        raise RuntimeError(
            f"github API forbidden (rate-limited?): {resp.text[:512].strip()}"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"github API returned {resp.status_code} for {url}")

    return _parse_entries(resp.json())


async def _fetch_blob(
    client: httpx.AsyncClient, entry: _ContentEntry
) -> bytes:
    """下载单个文件内容。优先用内联 base64，回退到 download_url。"""
    if entry.size > MAX_FILE_SIZE:
        raise RuntimeError(
            f"file {entry.path} too large: {entry.size} bytes (max {MAX_FILE_SIZE})"
        )
    # 内联 base64（小文件时 API 直接返回内容，省一次请求）
    if entry.encoding == "base64" and entry.content:
        clean = entry.content.replace("\n", "")
        return base64.b64decode(clean)
    # 回退到 download_url
    if not entry.download_url:
        raise RuntimeError(f"no download_url for {entry.path}")
    headers = {"User-Agent": "mewcode-install-skill"}
    resp = await client.get(entry.download_url, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"download {entry.download_url}: status {resp.status_code}")
    return resp.content


# ------------------------------------------------------------------
# 递归下载 + 安全校验
# ------------------------------------------------------------------

async def _walk_and_download(
    client: httpx.AsyncClient,
    src: SkillSource,
    subpath: str,
    local_dir: Path,
    report: InstallReport,
    depth: int,
) -> None:
    """递归遍历 GitHub 目录，下载所有文件到 local_dir。"""
    if depth > MAX_RECURSION_DEPTH:
        raise RuntimeError(f"install tree too deep (>{MAX_RECURSION_DEPTH} levels)")

    entries = await _list_contents(client, src, subpath)
    for entry in entries:
        if report.file_count >= MAX_FILE_COUNT:
            raise RuntimeError(f"install file count limit ({MAX_FILE_COUNT}) reached")

        # 防止路径穿越
        if ".." in entry.name or "/" in entry.name or "\\" in entry.name:
            raise RuntimeError(f"suspicious entry name: {entry.name!r}")

        target = local_dir / entry.name

        if entry.type == "file":
            data = await _fetch_blob(client, entry)
            if report.total_bytes + len(data) > MAX_TOTAL_SIZE:
                raise RuntimeError(
                    f"install total size limit ({MAX_TOTAL_SIZE} bytes) reached"
                )
            target.write_bytes(data)
            report.file_count += 1
            report.total_bytes += len(data)

        elif entry.type == "dir":
            target.mkdir(parents=True, exist_ok=True)
            await _walk_and_download(
                client, src, entry.path, target, report, depth + 1
            )
        # symlink / submodule 直接跳过


def _has_skill_manifest(directory: Path) -> bool:
    """检查目录下是否有 SKILL.md 或 skill.yaml（基本的合法 skill 检测）。"""
    return (directory / "SKILL.md").is_file() or (directory / "skill.yaml").is_file()


def _validate_skill_name(name: str) -> None:
    """校验 skill 名称：小写字母、数字、连字符、下划线，不能以 . 开头。"""
    if not name:
        raise ValueError("empty skill name")
    if name.startswith("."):
        raise ValueError("skill name cannot start with '.'")
    if not _VALID_NAME_RE.match(name):
        raise ValueError(
            f"skill name {name!r} contains invalid characters (use a-z 0-9 - _)"
        )


def user_skills_root() -> Path:
    """返回 ~/.mewcode/skills，不存在则自动创建。"""
    root = Path.home() / ".mewcode" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ------------------------------------------------------------------
# 安装主流程
# ------------------------------------------------------------------

async def install_skill(
    src: SkillSource,
    install_root: str | Path | None = None,
) -> InstallReport:
    """从 GitHub 拉取 skill 并原子安装到 install_root/<name>/。

    整个安装先写到临时目录，全部成功后再 rename 到最终位置，
    失败时不会留下残缺文件。
    """
    _validate_skill_name(src.name)

    root = Path(install_root) if install_root else user_skills_root()
    root.mkdir(parents=True, exist_ok=True)

    # 创建临时 staging 目录（与最终目录同级，保证 rename 是同一文件系统）
    staging = Path(tempfile.mkdtemp(prefix=f".install-{src.name}-", dir=str(root)))
    try:
        report = InstallReport(skill_name=src.name)

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            await _walk_and_download(client, src, src.subpath, staging, report, 0)

        # 校验：下载的目录里必须有 skill manifest
        if not _has_skill_manifest(staging):
            raise RuntimeError(
                "downloaded tree missing SKILL.md or skill.yaml — not a skill?"
            )

        # 原子替换：先删除旧安装（如果存在），再 rename
        final = root / src.name
        if final.exists():
            shutil.rmtree(final)
        staging.rename(final)
        report.target_dir = str(final)

        return report

    except Exception:
        # 安装失败时清理 staging 目录
        shutil.rmtree(staging, ignore_errors=True)
        raise
