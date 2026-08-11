# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""Linux bubblewrap（bwrap）沙箱实现。

通过 bwrap 创建隔离的用户命名空间，将根文件系统以只读方式挂载，
仅对白名单路径开放写权限。支持网络隔离（unshare-net）。
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from mewcode.sandbox import Sandbox, SandboxConfig


class BwrapSandbox(Sandbox):
    """Linux bubblewrap 沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        """构建 bwrap 命令行。

        基本结构：
          bwrap --unshare-user --unshare-pid
                --ro-bind / /                   # 根文件系统只读
                --bind <writable> <writable>     # 可写路径（读写挂载）
                --ro-bind <protected> <protected> # 禁写路径（强制只读覆盖）
                [--unshare-net]                  # 网络隔离
                --proc /proc                     # 挂载 /proc
                --dev /dev                       # 挂载 /dev
                -- bash -c <command>
        """
        args: list[str] = [
            "bwrap",
            "--unshare-user",
            "--unshare-pid",
            # 根目录只读挂载
            "--ro-bind", "/", "/",
        ]

        # 可写路径：用 --bind（读写）覆盖只读挂载
        for path in config.allow_write:
            resolved = str(Path(path).resolve())
            args.extend(["--bind", resolved, resolved])

        # 禁写路径：用 --ro-bind 强制只读（覆盖上面的 --bind）
        for path in config.deny_write:
            resolved = str(Path(path).resolve())
            args.extend(["--ro-bind", resolved, resolved])

        # 网络隔离
        if not config.network_enabled:
            args.append("--unshare-net")

        # 挂载 /proc 和 /dev（很多工具需要）
        args.extend(["--proc", "/proc"])
        args.extend(["--dev", "/dev"])

        # 分隔符 + 实际命令
        args.append("--")
        args.extend(["bash", "-c", command])

        return " ".join(shlex.quote(a) for a in args)

    def available(self) -> bool:
        """检查 bwrap 是否在 PATH 中。"""
        return shutil.which("bwrap") is not None
