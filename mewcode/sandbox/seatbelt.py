# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""macOS Seatbelt 沙箱实现。

通过 sandbox-exec -p <profile> 执行命令，利用 macOS 内核的 Seatbelt
框架限制进程的文件写入和网络访问。Profile 使用 SBPL（Sandbox Profile
Language）编写。
"""

from __future__ import annotations

import shlex
from pathlib import Path

from mewcode.sandbox import Sandbox, SandboxConfig

# sandbox-exec 二进制路径
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _build_profile(config: SandboxConfig) -> str:
    """根据 SandboxConfig 生成 SBPL profile 字符串。

    策略：deny-default 模式，显式放行必要的操作：
    - 允许进程执行和 fork（否则无法运行任何命令）
    - 允许 sysctl-read（很多程序启动时需要）
    - 全局允许文件读取
    - 按白名单允许文件写入，按黑名单禁止写入
    - 网络访问按配置开关
    """
    rules: list[str] = [
        "(version 1)",
        "(deny default)",
        # 基础权限：执行进程、fork 子进程、读取系统信息
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        # 全局文件读取权限
        '(allow file-read* (subpath "/"))',
    ]

    # 禁写路径（deny-write 优先级最高，放在 allow 之前让 Seatbelt 后匹配优先）
    # Seatbelt 的规则是后写优先，所以 deny 放在 allow 后面
    # 但为了逻辑清晰，我们先收集 allow，再追加 deny

    # 允许写入的路径
    for path in config.allow_write:
        resolved = str(Path(path).resolve())
        rules.append(f'(allow file-write* (subpath "{resolved}"))')

    # 禁止写入的路径（覆盖 allow，Seatbelt 后声明的规则优先）
    # 单文件用 literal 精确匹配，目录用 subpath 前缀匹配
    for path in config.deny_write:
        resolved = str(Path(path).resolve())
        matcher = "subpath" if Path(resolved).is_dir() else "literal"
        rules.append(f'(deny file-write* ({matcher} "{resolved}"))')

    # 网络访问控制
    if config.network_enabled:
        rules.append("(allow network*)")
    else:
        rules.append("(deny network*)")

    return "\n".join(rules)


class SeatbeltSandbox(Sandbox):
    """macOS sandbox-exec 沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        """将命令包装为 sandbox-exec 调用。"""
        profile = _build_profile(config)
        # 用 -p 参数传递内联 profile
        return f"{_SANDBOX_EXEC} -p {shlex.quote(profile)} bash -c {shlex.quote(command)}"

    def available(self) -> bool:
        """检查 sandbox-exec 是否存在。"""
        return Path(_SANDBOX_EXEC).is_file()
