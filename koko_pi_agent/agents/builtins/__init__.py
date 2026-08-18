# Koko Pi Agent
# 项目地址：https://github.com/xiaokekehaha/koko-pi-agent
"""内置子 Agent 定义（AgentLoader 三层覆盖里的兜底层）。

这些 .md 是随包分发的数据文件，没有任何代码 import 它们，所以清理式改动很容易
把它们当成普通文档删掉——2026-08 就发生过一次，四个内建 agent 静默消失。

BUILTIN_AGENT_FILES 就是为此存在的：它让「这一层应该有哪些文件」成为代码里可
grep、可引用的契约。AgentLoader 按这份清单加载，缺文件直接报错而不是降级成空
列表。要新增或移除内建 agent，必须同时改这里——这正是我们希望它是个有意识动作
的原因。
"""

BUILTIN_AGENT_FILES = (
    "explore.md",
    "general-purpose.md",
    "plan.md",
    "verification.md",
)
