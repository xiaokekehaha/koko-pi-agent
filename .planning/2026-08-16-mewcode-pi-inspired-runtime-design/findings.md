# Findings & Decisions

## Requirements
- 在新分支上做设计与规划。
- 使用 `planning-with-files` 技能持久化任务计划、发现和进度。
- 迭代当前 MewCode 项目；Pi 是参考架构，不是要实现的 Mini Pi。
- 继续遵守先设计、暂不修改生产源码的边界。
- 后续用户明确授权“开始开发，直到完成”，因此阶段 0 的生产代码实施边界已解除；ExtensionHost 仍不在本阶段范围。
- 设计文档使用 Markdown，术语尽量配通俗解释。

## Research Findings
- 当前 MewCode 已有 `Agent`、`ToolRegistry`、`CommandRegistry`、`HookEngine`、`SkillLoader`、CLI、Remote 和多 Agent 团队能力，不是从零开始。
- `mewcode/__main__.py`、`mewcode/remote.py` 和队友创建路径存在重复手工装配，统一组合根是高杠杆改进点。
- 当前 ToolRegistry 同名注册会静默覆盖；CommandRegistry 已经采用冲突快速失败。
- 当前 HookEngine 的异步 Hook 使用未被 Runtime 统一持有的任务，关闭与异常读取需要加强。
- 当前 `Agent.run()` 内触发 `session_start/end`，实际更接近一次 Agent Run；持久 Session、Agent Run 与 Turn 需要分开命名。
- Pi 官方 SDK 以 AgentSession 为主要应用入口，并由 ResourceLoader 提供扩展、Skill、Prompt、Theme 和上下文文件。
- Pi 扩展可以注册 Tool、Command 和事件；项目本地扩展只有在项目可信后才加载，扩展拥有宿主进程的完整系统权限。
- Pi 把 `session_start/shutdown` 与 `agent_start/end`、`turn_start/end` 分开，适合作为 MewCode 生命周期语义的参考。
- Python 标准库 `AsyncExitStack` 支持同步和异步资源组合，并按反向顺序执行清理，适合实现扩展资源账本。
- Python `importlib.metadata.entry_points()` 适合作为已安装扩展包的标准发现机制。
- pluggy 擅长 Hook 规格、插件注册和一对多 Hook 调用，但不直接解决 MewCode 的 Tool/Command 所有权、多 Agent 会话隔离和异步资源清理。
- 工作区已有未跟踪的 `examples/mini_pi_agent/` 和测试；它们应视为独立学习材料，不应成为当前产品设计的实现基线。
- “small core”在本设计中只表示核心职责稳定、变化原因少，不表示 MewCode 功能减少；为避免误解，主文档统一使用“稳定核心 + 可扩展 Runtime”。
- Pi 第 1 章的关键不是插件数量，而是一个无状态 Loop 被 `Agent` 和 `AgentHarness` 两种组合共同复用；Core 明确拒绝模型厂商、UI、持久化和具体 Runtime 依赖。
- Pi 第 2 章把一次运行拆成 run、turn、message、tool 四层事件，并把“事件结束”与“彻底 idle”分开定义。
- Pi 的 Tool 执行先顺序 prepare，再允许 execute 并发，最后 finalize；若模型输出因长度截断，所有 Tool Call 都只返回错误而不执行。
- Pi 在 LLM 调用前提供 `transformContext` 与 `convertToLlm` 两个 Gate，使内部 AgentMessage 与 Provider 协议只在调用边缘相遇。
- 当前 MewCode `Agent.run()` 同时承担环境注入、记忆、Hook、压缩、模型流、Tool 调度、权限、恢复和事件，Interface 背后没有独立的可复用 Loop Seam。
- 当前 `Agent.run()` 与 `run_to_completion()` 各自实现模型 → Tool → 模型循环；Thinking、Hook、并发、权限、重试和事件行为已经不同。
- 当前 `pre_tool_use/post_tool_use` 只在 `_execute_tool_noninteractive()` 路径调用，交互 `run()` 的两个 Tool 执行路径未走同一 Hook 管线。
- 当前 `StreamingExecutor` 在完整 Assistant Message 结束前启动 Tool；`stop_reason == max_tokens` 时主循环会在 `collect_results()` 前继续下一轮，存在已执行任务未收集的安全风险。
- 当前 `partition_tool_calls()` 和 `is_concurrency_safe` 有测试，但生产 `Agent.run()` 未调用该分组函数，说明测试面没有覆盖真实 Tool 调度 Interface。
- 当前并发保护主要位于 TUI/Remote 的 `_streaming` 标志，生产 `Agent` 自身没有单 active-run 不变量或可供旁观者等待的 settlement Interface。
- `run_to_completion()` 不是边缘兼容方法，而是 TaskManager、AgentTool、in-process teammate 等多条生产路径的共同入口；统一循环必须先提供 Headless Adapter，再删除旧实现，不能直接让子 Agent 改走 TUI 语义。
- Skill 的 fork 路径又直接消费 `Agent.run()` 事件，说明调用方真正需要的是同一个 Run 的不同结果 Adapter：流式 UI、文本结果、后台任务状态，而不是多份 Loop Implementation。
- 阶段 0 实施后，生产 Agent 的模型循环只存在于 `mewcode/runtime/agent_loop.py`，Tool 的 `execute()` 生产调用只存在于 `mewcode/runtime/tool_pipeline.py`。
- `Agent.run()` 与 `run_to_completion()` 现在都是 Adapter：前者把 async EventSink 转成兼容 async iterator，后者消费同一个 AgentRun 并返回 `RunResult.final_text`。
- `ToolPipeline` 先按声明顺序 prepare，再把连续 concurrency-safe Tool 放入 `asyncio.TaskGroup`；UI completion event 可按完成顺序到达，Conversation result 始终恢复声明顺序。
- `max_tokens` / `length` 响应中的 Tool Call 会生成配对错误结果但执行次数为零；原 streaming 抢跑逻辑与对应浅测试已删除。
- `AgentRun.cancel()` 会取消主 Run task；若 Assistant Tool Message 已入历史，AgentLoop 在退出前写入取消结果，保持消息配对，然后才发 `RunFinished` 并进入 idle。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 目标命名为 MewCode Pi-inspired Runtime | 避免把参考架构误解为另做 Mini Pi |
| 新增统一 AgentRuntime 组合根 | 收拢 CLI、Remote 与队友的重复装配，同时保留现有 Agent Core |
| ExtensionHost 作为深模块 | 用小 Interface 吸收发现、所有权、回滚、清理和诊断复杂度 |
| ExtensionCatalog 与 ExtensionSession 分离 | 同一扩展工厂可为多个 Agent 创建隔离实例，也为未来进程级共享资源预留空间 |
| 使用 AsyncExitStack 和 TaskSupervisor | 自动托管注册、连接和跨轮次后台任务的清理 |
| Observer 与 Interceptor 分开 | 明确是否可修改或阻止流程，并定义不同失败策略 |
| 第一版不引入 pluggy | 先解决当前最直接的所有权和生命周期问题，保留 EventPipeline 内部替换 Seam |
| 第一版不做通用 Service/Inject 容器 | 当前真实扩展点是 Tool、Command、Hook 和 Skill，避免超前抽象 |
| 每个实施阶段限制为清晰的纵向切片 | 保证可以独立合并、验证和回滚，不让架构迁移长期停在双轨状态 |
| 在插件阶段前先实施 Loop/Tool 阶段 0 | 安全语义和唯一执行路径是 ExtensionHost 依赖的地基，顺序倒置会把分叉固化进新 Runtime |
| 以 `AgentLoop` 作为深模块候选 | 删除它会迫使 interactive、Remote 和子 Agent 重写同一套循环，符合删除测试 |
| 以 `ToolPipeline` 作为独立深模块候选 | 参数校验、权限、Hook、并发、安全截断和结果排序应通过一个小 Interface 获得高 Leverage |
| 不照搬 Pi 的 TypeScript 类型和浏览器包边界 | Python 应使用 async generator、TaskGroup 和显式 Adapter 表达同一语义，而非复制实现形式 |
| 阶段 0 采用兼容 facade 而不是修改所有调用签名 | TUI、Remote、Skill、TaskManager、AgentTool 和 teammate 可继续使用原入口，但实际共享同一 AgentRun 与 AgentLoop |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 初稿“Pi 式小核心”存在产品定位歧义 | 主文档改名并明确“主体是 MewCode，Pi 只是参考” |
| 工作区已有未跟踪 Demo 与文档 | 全部视为用户现有内容；不覆盖、不删除、不当作实施授权 |

## Resources
- Pi repository: https://github.com/earendil-works/pi
- Pi extensions: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md
- Pi SDK: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md
- Python contextlib: https://docs.python.org/3/library/contextlib.html
- Python importlib.metadata: https://docs.python.org/3/library/importlib.metadata.html
- pluggy: https://pluggy.readthedocs.io/en/stable/
- Existing Cordis learning design: `docs/plugin-agent-learning-design.md`
- Main design: `docs/mewcode-pi-inspired-runtime-design.md`
- Pi chapter 1: https://books.antinomie.org/pi/chapter/01
- Pi chapter 2: https://books.antinomie.org/pi/chapter/02
