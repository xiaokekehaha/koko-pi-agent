# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    from textual.drivers.windows_driver import WindowsDriver as _BaseDriver
else:
    from textual.drivers.linux_driver import LinuxDriver as _BaseDriver


class NoAltScreenDriver(_BaseDriver):
    """跳过备用屏（alternate screen）的 driver，让输出保留在主终端的
    滚动回看（scrollback）区域中，方便用户向上翻阅历史交互记录。
    自动根据平台选择 LinuxDriver 或 WindowsDriver 作为基类。

    原理：去掉 alt screen 切换码，并在进入应用模式时输出足够多的空行，
    将已有终端内容推入 scrollback，Textual 在"新页面"上渲染。"""

    def start_application_mode(self):
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        # 在 Textual 接管终端之前，用换行把已有内容推入 scrollback
        sys.stdout.write("\n" * rows)
        sys.stdout.flush()
        super().start_application_mode()

    def write(self, data: str) -> None:
        if "\x1b[?1049h" in data:
            data = data.replace("\x1b[?1049h", "")
        if "\x1b[?1049l" in data:
            data = data.replace("\x1b[?1049l", "")
        if data:
            super().write(data)
