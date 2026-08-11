# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

import asyncio
import re
import shlex
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.sandbox import Sandbox, SandboxConfig

MAX_TIMEOUT = 600

# 特殊命令的退出码语义映射
# 这些命令的 exit code 1 不代表错误，只有 >= 阈值才算真正的错误
# 例如 grep 返回 1 仅表示"没有匹配行"，不是执行出错
_COMMAND_ERROR_THRESHOLDS: dict[str, int] = {
    "grep": 2,   # exit 1 = 没有匹配到内容
    "egrep": 2,
    "fgrep": 2,
    "rg": 2,     # ripgrep，与 grep 语义一致
    "diff": 2,   # exit 1 = 文件内容有差异
    "find": 2,   # exit 1 = 部分成功（如权限不足跳过某些目录）
    "test": 2,   # exit 1 = 条件为假
    "[": 2,      # test 的别名形式
}


def _extract_last_command_name(command: str) -> str | None:
    """从命令字符串中提取最后一个管道段的基础命令名。

    管道中最后一个命令决定了整体退出码，所以只看最后一段。
    例如 "cat file | grep pattern" → "grep"
    """
    # 按管道符拆分，取最后一段
    last_segment = command.rsplit("|", maxsplit=1)[-1].strip()
    if not last_segment:
        return None

    # 跳过常见的环境变量赋值前缀，如 "FOO=bar command ..."
    # 也要处理 sudo/env 等包装命令
    try:
        tokens = shlex.split(last_segment)
    except ValueError:
        # shlex 解析失败时，用简单的空格分割兜底
        tokens = last_segment.split()

    for token in tokens:
        # 跳过形如 VAR=VALUE 的环境变量赋值
        if re.match(r"^[A-Za-z_]\w*=", token):
            continue
        # 取 basename（去掉路径前缀，如 /usr/bin/grep → grep）
        base = token.rsplit("/", maxsplit=1)[-1]
        return base

    return None


def _interpret_exit_code(command: str, exit_code: int) -> bool:
    """根据命令语义判断退出码是否代表真正的错误。

    返回 True 表示是错误，False 表示不是错误。
    """
    if exit_code == 0:
        return False

    cmd_name = _extract_last_command_name(command)
    if cmd_name and cmd_name in _COMMAND_ERROR_THRESHOLDS:
        # 只有退出码 >= 阈值时才视为错误
        return exit_code >= _COMMAND_ERROR_THRESHOLDS[cmd_name]

    # 默认行为：非零退出码即为错误
    return True


# 特殊命令的退出码提示信息
# 帮助 LLM 理解非零退出码的含义，而不是简单地标记为错误
_EXIT_CODE_HINTS: dict[str, str] = {
    "grep": "no matches found",
    "egrep": "no matches found",
    "fgrep": "no matches found",
    "rg": "no matches found",
    "diff": "files differ",
    "find": "some directories were inaccessible",
    "test": "condition is false",
    "[": "condition is false",
}


def _exit_code_hint(command: str, exit_code: int) -> str:
    """为非零退出码生成可读提示。

    对于特殊命令（grep/diff/test 等），附加语义说明让 LLM 理解退出码含义。
    普通命令只显示退出码数字。
    """
    cmd_name = _extract_last_command_name(command)
    hint = _EXIT_CODE_HINTS.get(cmd_name, "") if cmd_name else ""
    if hint:
        return f"Exit code {exit_code} ({hint})"
    return f"Exit code {exit_code}"


class Params(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=120, description="Timeout in seconds (max 600)")


class Bash(Tool):
    name = "Bash"
    description = "Execute a shell command and return stdout and stderr."
    params_model = Params
    category = "command"

    # 工作目录，为 None 时使用当前进程的工作目录
    work_dir: str | None = None

    # OS 级沙箱实例和配置（由外部注入，为 None 时不启用沙箱）
    sandbox: Sandbox | None = None
    sandbox_config: SandboxConfig | None = None

    async def execute(self, params: Params) -> ToolResult:
        timeout = min(params.timeout, MAX_TIMEOUT)

        # 如果启用了 OS 沙箱，将命令包装为沙箱内执行
        actual_command = params.command
        if self.sandbox and self.sandbox_config and self.sandbox.available():
            actual_command = self.sandbox.wrap(params.command, self.sandbox_config)

        try:
            proc = await asyncio.create_subprocess_shell(
                actual_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # 合并 stderr 到 stdout
                cwd=self.work_dir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(output=f"Error: command timed out after {timeout}s", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error executing command: {e}", is_error=True)

        # 合并流输出，不再区分 stdout/stderr
        output = stdout.decode(errors="replace") if stdout else ""

        # 非零退出码时追加退出码信息，但 is_error 始终为 False
        # 只有超时和异常才设置 is_error=True
        exit_code = proc.returncode or 0
        if exit_code != 0:
            hint = _exit_code_hint(params.command, exit_code)
            if output:
                output = f"{output.rstrip()}\n\n{hint}"
            else:
                output = hint

        if not output:
            output = "(no output)"

        return ToolResult(output=output, is_error=False)

