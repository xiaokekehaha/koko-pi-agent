# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import tempfile
from pathlib import Path


class PathSandbox:

    # 默认禁写路径：这些文件包含敏感配置，不允许 Agent 直接修改
    _DEFAULT_DENY_WRITE: list[str] = [
        ".mewcode/config.yaml",
        ".mewcode/permissions.local.yaml",
        ".mewcode/skills/",
    ]

    def __init__(
        self,
        project_root: str,
        extra_allowed: list[str] | None = None,
        deny_write: list[str] | None = None,
    ) -> None:
        root = Path(project_root).resolve()
        self._allowed_roots: list[Path] = [root, Path(tempfile.gettempdir()).resolve()]
        if extra_allowed:
            for p in extra_allowed:
                self._allowed_roots.append(Path(p).resolve())

        # 禁写路径列表：相对路径基于 project_root 解析
        self._deny_write: list[Path] = []
        for dp in (deny_write or self._DEFAULT_DENY_WRITE):
            dp_path = Path(dp)
            if not dp_path.is_absolute():
                dp_path = root / dp_path
            self._deny_write.append(dp_path.resolve())


    @property
    def project_root(self) -> Path:
        return self._allowed_roots[0]


    def _is_deny_write(self, real_path: Path) -> bool:
        """检查路径是否命中禁写列表。

        支持目录前缀匹配：如果禁写项以 / 结尾或本身是目录，
        则该目录下的所有文件都被禁止写入。
        """
        for deny_path in self._deny_write:
            # 精确匹配
            if real_path == deny_path:
                return True
            # 目录前缀匹配
            try:
                real_path.relative_to(deny_path)
                return True
            except ValueError:
                continue
        return False


    def check(self, path: str) -> tuple[bool, str]:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.project_root / p
        abs_path = p.absolute()

        try:
            real_path = abs_path.resolve(strict=True)
        except OSError:
            ancestor = abs_path
            while not ancestor.exists():
                parent = ancestor.parent
                if parent == ancestor:
                    return False, f"无法解析路径: {path}"
                ancestor = parent
            try:
                resolved_ancestor = ancestor.resolve(strict=True)
            except OSError:
                return False, f"无法解析路径: {path}"
            real_path = resolved_ancestor / abs_path.relative_to(ancestor)

        # 禁写检查优先于允许检查
        if self._is_deny_write(real_path):
            return False, f"路径 {path} 在禁写列表中"

        for root in self._allowed_roots:
            try:
                real_path.relative_to(root)
                return True, ""
            except ValueError:
                continue

        return False, f"路径 {path} 超出沙箱范围"
