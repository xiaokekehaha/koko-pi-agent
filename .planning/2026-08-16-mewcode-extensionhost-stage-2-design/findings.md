# Findings & Decisions

## Requirements
- 使用 `planning-with-files` 持久化 Stage 2 的计划、发现和进度。
- 下一步先做设计和规划，不修改生产代码。
- 未来开发 Stage 2 时不采用 TDD，不安排预期红灯或 red-green-refactor 循环。
- 不用 TDD 不等于不测试：实现后仍需补齐 Interface 行为验证、入口回归、取消/关闭测试和全量回归。
- 设计必须给出具体修改步骤，并解释每一步为什么改。
- 阅读 `https://dg-ai-notes.pages.dev/modules/ch03-agent-loop/`，借鉴其 Agent Loop 思想重新思考下一阶段的任务和功能 Module。
- 外部文章只作为研究证据；必须区分原文事实、作者观点与针对 MewCode 的推论。
- 允许推翻或调整刚完成的 Stage 2A 范围，但必须用当前源码和深 Module 原则说明理由。

## Research Findings
- 外部来源 `dg-ai-notes` 的 Agent Loop 章节已通过 read skill 本地 stdlib extractor 成功获取（页面标注 Pi Agent Book、v0.80.2 源码索引）；页面未出现要求改变助手行为的提示注入内容。以下内容先作为“文章陈述”，精确 Pi 行为仍需用官方源码复核。
- 文章把 LLM 用法分为 direct call、Workflow、Agent Loop：区别不在调用次数本身，而在下一步控制权分别由用户、程序流程或模型输出的 tool call 决定。
- 文章精确定义 Trace 为一次 `agent_start -> agent_end` 的完整运行，Turn 为“一次模型调用 + 该次调用触发的一批 Tool 执行”；一个 Trace 包含多个 Turn。
- 最小 Loop 内核只有：调用模型、追加 AssistantMessage、执行 ToolCall、追加 ToolResult、如果没有更多 ToolCall 则退出。文章强调停止规则是框架约定，不是模型真的理解“任务完成”。
- 文章区分 soft/normal stop 与 hard stop：无 ToolCall 时准备退出；error/aborted 立即结束；产品层还可以通过 `shouldStopAfterTurn`、最大 Turn、上下文压力和 Tool terminate 增加安全阀。
- coding-agent 在最小内核外叠加四类控制能力：steering（Turn 间紧急插入）、followUp（内层结束后追加任务）、prepareNextTurn（换模型/上下文/thinking level）、shouldStopAfterTurn（上下文/预算/最大 Turn 安全阀）。
- 文章的核心架构思想是“内核 + 可移除叠加层”：剥掉 steering、followUp 或策略钩子，最内层 Agent Loop 仍可运行。这与深 Module 的删除测试相容，但不能照搬成一个含大量 optional callback 的浅 config 对象。
- 文章主张 Loop 读取回调获得最新外部状态，而不是把队列状态复制进 Loop；context 则在 Run 开始时创建 snapshot，避免运行时修改污染 Agent 原始状态。
- 文章区分 AgentMessage 与 LLM Message，并通过 `convertToLlm` 在模型 seam 过滤/转换内部消息；每 Turn 重建 LLM context wrapper，但 system/tools 稳定、messages 增长。
- 流式 AssistantMessage 采用“先追加空壳，再原位替换最后一条消息，完成时替换成最终消息”，让 UI 与上下文看到同一个正在生长的消息槽位。
- Tool batch 的文章设计是：准备/验证/before hook 顺序进行，真正 execute 可并行，ToolResult 按调用顺序写回；只要存在必须串行的 Tool，整批保守串行。
- 文章强调 steering 与 followUp 语义不同：steering 是当前 Trace 的 Turn 间插队；followUp 是内层已自然停止后，在同一 Trace 中续命。
- 对 MewCode 的第一层启发不是“再实现一个 Loop”，而是检查 Stage 0 AgentLoop 是否已经把这些产品控制能力集中成清晰 Module，还是把 Context、停止策略、排队输入和 Turn 变更散在 TUI/Remote/AgentLoop 内。
- Stage 1 已完成 Tool-only 纵向切片：Tool contribution/owner/handle、ExtensionHost/Session、四个 ToolProfile、AgentRuntime、borrowed ToolView 和 MCP 可逆注册均已有实现与回归证据。
- Stage 1 明确推迟 Command、事件、通用资源、后台任务、外部扩展发现和 reload；Stage 2 需要重新选择最小切片，不能默认全部纳入。
- 当前用户原有的 Mini Plugin Agent 与 Cordis 文档是教学材料，不是 MewCode 生产 Stage 2 的实现授权或设计基线。
- `codebase-design` 的约束是：外部 Interface 要小，复杂所有权和清理留在 Implementation；测试与调用方跨同一 seam；只有真实变化点才引入 Adapter。
- 依赖必须按 in-process、local-substitutable、remote-owned、true external 分类，再决定 seam 和验证方式。
- 主路线原先把 Stage 2 分为 2A 和 2B：2A 是 Command、通用资源与受控后台任务；2B 才是 Observer、Interceptor 和现有 Hook Adapter。
- Stage 1 完成结论进一步收窄了审批门：下一步可优先讨论通用资源与后台任务所有权，Command、事件、发现和 reload 都不因 Stage 1 完成而自动进入范围。
- `ExtensionSession` 已经内部使用 `AsyncExitStack` 做 Tool contribution 回滚，但还没有面向扩展的资源托管 Interface；Stage 2 可以复用已有事务和 LIFO 清理能力，而不是新建第二套生命周期框架。
- 当前 `CommandRegistry` 只提供注册和冲突检查，没有来源、RegistrationHandle 或注销；TUI 与 Remote 各自创建 Registry，prompt/teammate 没有同等 Command 入口，因此 Command 迁移会扩大入口与交互语义范围。
- 当前 `TaskManager` 管理的是用户可见的后台 Agent 任务，不等同于“扩展后台协程”；Stage 2 不应把两者混成一个 Interface。
- 仓库存在多处裸 `asyncio.create_task()`：AgentLoop 的记忆提取、TUI 消息/UI 辅助任务、Remote 消息处理、Skill fork、in-process teammate 等。通用 `TaskSupervisor` 若试图一次接管全部任务，会明显超出扩展所有权切片。
- MCP client 自己已有 `AsyncExitStack`，MCPManager 有独立 shutdown 和 Tool Handle；它是验证通用资源 seam 的候选 Adapter，但不能在没有明确连接失败/关闭语义前机械迁入 ExtensionSession。
- 现有 HookEngine 是 2B 候选，不应为了证明 TaskSupervisor 而提前改写事件模型。
- `CommandRegistry` 当前有两个注册入口：async `register()` 使用锁，生产装配基本走无锁的 `register_sync()`；两者都做 name/alias 快速冲突，但都不返回 Handle，也没有 unregister、owner、source 或 generation。
- Command 本身是带闭包 handler 的进程内对象，执行时依赖一个较大的 `CommandContext`（Agent、Conversation、Session、Memory、UI、config 等）；如果直接把整个 Context 塞进 ExtensionAPI，会把交互入口细节泄漏进 Host Interface。
- TUI 在构造和 provider 切换时整表重建 CommandRegistry，随后手工注册 Skill、Worktree、Tasks、Trace 等依赖运行期对象的命令；Remote 只注册公共内置命令，prompt 与 teammate 没有斜杠命令入口。
- TUI 的 provider 切换通过“丢弃旧 Registry”获得事实上的批量注销，而不是精确 Handle 清理；这会掩盖扩展动态 Command 的 stale handler 问题。
- 公共内置 Command 清单是静态 Definition，依赖运行期对象的命令则是 factory；这与 Stage 1 的 Tool manifest 模式相似，但 Command 的可用入口 profile 与 Tool profile 不相同。
- Command 执行、补全和命令列表都直接依赖调用方持有的 Registry。若 Stage 2 纳入 Command，AgentRuntime 不能只返回 Agent；需要明确 interactive runtime view 或由入口 Adapter 持有 Session 提供的 Registry。
- Stage 1 已为每个 extension 创建独立 `AsyncExitStack`，再把 extension scope 的 `aclose()` 反向压入 session scope；因此 Stage 2 的 ResourceScope 应深化这条现有 seam，而不是平行创建另一份资源账本。
- `ExtensionAPI` 当前只在 `activating` 阶段允许 `register_tool()`；资源/清理/任务如果同样仅在 installer 激活期登记，可以保持 API 失效和 generation 语义，不必提前开放 active 期动态注册。
- `ExtensionSession.aclose()` 已有 active -> closing -> closed 和幂等入口，但资源清理异常目前会向外传播，Diagnostics 没有资源名、任务名、清理失败或超时字段；Stage 2 需要定义“继续清理剩余项 + 汇总诊断”的确切语义。
- `AgentRuntime` 的关闭顺序是取消并等待 active AgentRun，再关闭 borrowed ToolView 和 ExtensionSession；扩展任务必须在 Session close 内取消/等待，不能与 AgentRun 共用一个裸 task 列表。
- MCPClient 内部已经正确用 `AsyncExitStack` 管理 stdio/http/ClientSession；MCPManager 则拥有多个 client 与 Tool Handle。它适合作为后续迁移的真实 async-closeable Adapter，但当前连接发生在 Runtime 激活之后，不能在 Stage 2 未放宽 active API 时强行塞入 installer。
- `TaskManager` 是面向用户的后台 Agent 作业目录：保存结果、token、通知、mailbox 和 cancel；它没有统一 `aclose()`，但不应被改名或复用成 Extension `TaskSupervisor`。
- HookEngine 的 `async_exec` 直接 `asyncio.ensure_future()` 且不保存 task；异常虽然在 `_run_single()` 内转成通知，但 Runtime 关闭无法取消或等待这些 Hook。它是 Stage 2B 接入 TaskSupervisor 的直接动机。
- AgentLoop 的周期记忆提取/整合、TUI 的 MCP/UI/通知/消息任务、Remote 的消息处理和 teammate 后台运行分别属于 Run、App/入口或团队生命周期。Stage 2A 的 Extension TaskSupervisor 不能声称接管这些非扩展任务。
- 若 TaskSupervisor 只管理 installer 创建的扩展任务，其依赖是纯 in-process asyncio；不需要额外 Adapter。文件/连接资源则由具体 context manager 自带 Adapter，ResourceScope 外部 Interface 无需知道类型。
- 现有 Command 测试覆盖解析、补全、基本冲突、内置 handler 和静态清单，但没有 owner/source/handle、两个 Registry 隔离、动态刷新或关闭后 stale handler 的行为证据。
- Skill Command 刷新依赖进程全局 `_REGISTERED_SKILL_NAMES`，并直接修改 Registry 私有 `_commands/_alias_map`；多个 TUI/Remote Registry 或 provider 切换时，这个全局集合不是可靠 owner。它是 Command 所有权值得重构的证据，也说明该切片不能只补一个 unregister 方法。
- Markdown 自定义 Command loader 当前只导出且有测试，没有生产入口调用；Stage 2 若迁 Command，不应顺带把 loader/discovery 接入，否则会把 Stage 3 的发现范围提前带入。
- TUI provider 切换会 cancel 通知和 stale-cleanup task，但没有 await 两者完成；退出也只 cancel stale-cleanup。它是任务所有权缺失的真实证据，但这些 task 目前属于 App 生命周期。
- TUI 的 Hook startup 使用裸 `ensure_future()`；shutdown 临时创建 task、最多等待 3 秒后 cancel。Stage 2A 可提供 TaskSupervisor 基础，但 Hook 接入仍应在 2B 随事件语义一起迁移。
- 两个适合 Stage 2A tracer bullet 的真实 Adapter 是：`MCPManager.shutdown()`（true external 连接资源，通过本地 async cleanup 接入）和 TUI worktree stale cleanup coroutine（local-substitutable/in-process 长任务）。前者验证资源反向关闭，后者验证任务取消等待。

## Dependency Classification
| Candidate | Category | Current owner | Stage 2 implication |
|-----------|----------|---------------|---------------------|
| Tool/Command registries | in-process | ExtensionSession 或入口 | 可用真实对象直接验证，无需新 port |
| Extension TaskSupervisor | in-process asyncio | 尚不存在 | 作为 ResourceScope 内部 Module，测试跨公开 Interface |
| Worktree stale cleanup | local-substitutable + in-process task | TUI App | 可作为受控任务 tracer bullet，但不把整个 WorktreeManager 搬入 Host |
| MCPManager/MCPClient | true external | TUI/Remote/teammate 入口 | 只把关闭所有权交给 ResourceScope；网络 client 仍是现有 Adapter |
| Hook command/http actions | true external | HookEngine | 2B 再通过 Event/Hook Adapter 接入 supervisor |
| Background Agent TaskManager | in-process + Agent runtime | TUI/Remote/AgentTool | 保持独立用户能力，不实现 Extension TaskSupervisor Interface |
| Memory/session/file history | local-substitutable | 入口/Agent | 本阶段不迁移，除非发现明确泄漏或第二个真实 Adapter 需求 |

## Candidate Slice Comparison
| Candidate | Depth / leverage | Real adapters now | Coupling / risk | Decision |
|-----------|------------------|-------------------|-----------------|----------|
| Command contribution ownership | 中：可统一 owner、handle、冲突和刷新 | TUI/Remote registry、Skill Command | 强耦合 `CommandContext`、入口 profile、Skill 私有状态；loader 尚未进生产 | defer，后续独立 Stage 2C |
| ResourceScope + TaskSupervisor | 高：一次实现统一启动回滚、关闭、取消、超时和诊断 | MCPManager cleanup、worktree stale-cleanup task | 可完全复用 ExtensionSession seam；不改 AgentLoop | select，作为 Stage 2A |
| EventPipeline + Hook Adapter | 高，但依赖受控任务先存在 | HookEngine、阶段 0 events | 观察与拦截决策面较大，且未跟踪 Hook task 正需要 supervisor | defer，保持 Stage 2B |

删除 `ResourceScope` 的结果是：Host、MCP/TUI/Remote/teammate 各自重新维护 AsyncExitStack、task list、取消超时、清理顺序和错误汇总，因此它能显著集中复杂度，满足深 Module 的删除测试。

## Selected Stage 2A Interface
Stage 2A 只给 `ExtensionAPI` 增加三个激活期能力，调用方仍只认识 `ExtensionHost.open_session()` 与 `AgentRuntime`：

```python
class ExtensionAPI:
    async def acquire(self, name: str, manager: ContextManager[T] | AsyncContextManager[T]) -> T: ...
    def defer(self, name: str, cleanup: Callable[[], object | Awaitable[object]]) -> None: ...
    def start_task(self, name: str, awaitable: Awaitable[None]) -> ExtensionTaskHandle: ...
```

- `acquire()` 始终由调用方 `await`，内部自行识别同步/异步 context manager，避免暴露两套几乎相同的 Interface。
- `defer()` 接纳没有 context-manager Interface 的旧资源，例如现有 `MCPManager.shutdown()`；清理函数可同步或异步。
- `start_task()` 只接纳扩展拥有的长生命周期协程；返回只读 Handle（name/status/done），不暴露原始 `asyncio.Task`。
- 三个方法与 `register_tool()` 一样只允许 `activating` 阶段调用；Session active 后继续禁止动态登记，避免提前引入 stale API 与 reload 语义。
- ResourceScope 与 TaskSupervisor 是 Host Implementation，不作为入口组合根的新参数，也不让扩展直接拿到底层 AsyncExitStack。

## Lifecycle and Failure Semantics
1. Host 为每个 extension 创建一个 ResourceScope；API 的 Tool Handle、资源、cleanup 和 task 都记在该 scope。
2. installer 成功后 API sealed；失败或取消时先 sealed，再关闭该 extension scope。
3. 正常 Session close 按 extension 激活逆序关闭。
4. 单个 scope 内按“撤销 Tool/未来 Command contribution -> 取消并等待 task -> LIFO 关闭资源/cleanup”执行，防止新工作进入即将关闭的依赖。
5. task 正常完成：读取结果并从 active 集合移除；task 抛错：读取异常并追加 `task_failed` diagnostic，不制造 never-retrieved warning，也不自动关闭整个 Runtime。
6. 关闭时取消未完成 task，并在可配置但由 Host 统一给出的超时内等待；忽略取消者记 `task_cancel_timeout`/`leaked`，继续关闭资源。
7. 单个 cleanup 失败时记录名称、extension、source 和错误，继续清理其他项；全部结束后用一个聚合 `ExtensionCloseError` 向调用方报告，Session/Runtime 状态仍必须是 closed。
8. installer 被取消时必须原样传播 `CancelledError`；回滚错误进入 diagnostics，不得遮蔽取消。
9. `AgentRuntime.diagnostics` 不再只复制 open 时快照，而应组合 Session 的实时 diagnostics 与 Runtime 自己的 leak diagnostics，使后台 task 失败在运行期可见。

## Compatibility Decisions
- `SessionContext.profile` 已开始控制非 Tool extension；Stage 2A 将 `ToolProfile` 更名为 `RuntimeProfile`，保留 `ToolProfile = RuntimeProfile` 兼容别名，入口逐步改用新名称。
- 不改变 Tool 名称、Schema、Command 格式、Hook YAML、配置文件或 Session JSONL。
- MCP Tool 仍由 MCPManager 保存 RegistrationHandle；Stage 2A 只迁移 manager/client 的关闭所有权，不开放 active-phase `ExtensionAPI.register_tool()`。
- `TaskManager`、AgentRun、UI message task、memory extraction 和 Hook event 仍保留原 owner。

## Internal Module Design

### ResourceScope
- 每个 ExtensionDefinition 激活实例一个 scope，不跨 extension 共享。
- 内部维护 contribution cleanup、TaskSupervisor、resource cleanup 三类账本；账本项包含 name、kind、sequence、extension owner 和 cleanup callable。
- `aclose()` 不在首个错误处停止，而是返回全部 `ExtensionCleanupFailure`；由 ExtensionSession 在所有 scope 都关闭后统一构造 `ExtensionCloseError`。
- contribution 先撤销，task 再取消等待，普通 resource 最后按 sequence 逆序关闭。这样能力不可再进入后，后台逻辑停止，底层连接/文件才释放。
- 第一次 close 无论成功失败都最终进入 closed；重复 close 返回空失败列表，不重复调用 cleanup。

### TaskSupervisor
- 只保存通过当前 ExtensionAPI 创建的 `asyncio.Task[None]`，任务带 extension_id、name 和内部 sequence。
- done callback 必须读取 `task.exception()`；`CancelledError` 视为正常取消，其他异常追加实时 `task_failed` diagnostic。
- shutdown 使用“对所有 active task 调用 cancel -> `asyncio.wait(..., timeout=...)` -> 消费 done -> 标记 pending timeout”，不用可能因协程吞取消而无限延长的逐个 `wait_for()`。
- 超时 task 保留内部引用与 done callback，诊断标记 leaked；Runtime 不声称已强制终止 Python coroutine。
- 后台任务启动不等于 readiness。若 extension 启动依赖连接 ready，installer 必须在返回前显式 await；`start_task()` 后的异步失败只使 Runtime degraded，不自动触发关闭。

### Diagnostics and Errors
现有 `ExtensionDiagnostic` 增加兼容默认字段：`kind="extension"`、`name=""`、`phase=""`；保留已有 extension_id/source/status/error 字段和现有构造方式。

新增：
- `ExtensionCleanupFailure(extension_id, source, kind, name, error)`；
- `ExtensionCloseError(failures)`，继承 RuntimeError，消息包含每项资源名和原因；
- status：`task_failed`、`task_cancel_timeout`、`cleanup_failed`、`resource_leaked`，既有 `activated/failed/leaked` 保留。

`ExtensionSession.diagnostics` 是生命周期内持续更新的只读 snapshot；`AgentRuntime.diagnostics` 每次读取时组合 Session diagnostics 与 Runtime-local diagnostics，不再在 open 时冻结。

### Built-in Resource Adapter
Catalog 增加第二个真实 Definition：`mewcode.runtime-resources`。它从 typed bindings 读取：
- 入口在 Runtime 打开前预创建的 `MCPManager`，用 `api.defer("mcp-manager", manager.shutdown)` 托管关闭；
- TUI 的 `stale_cleanup_factory`，用 `api.start_task("worktree-stale-cleanup", factory())` 托管循环任务。

Definition 本身不连接 MCP；TUI/Remote/teammate 仍在 Runtime active 后调用现有 `register_all_tools()`。差别是 manager 在连接前已经有 owner，即使连接取消或异常也会随 Runtime 回滚/关闭。

### State and Concurrency Invariants
1. `open_session()` 未返回前，Runtime 不可见；资源登记失败按关键 extension 规则回滚。
2. API 仅 activating 可用；active/closing/closed 均拒绝 acquire/defer/start_task/register_tool。
3. 同一 Session 的 `aclose()` 幂等；并发 close 由 lock 或单一 close future 汇合，cleanup 只运行一次。
4. Runtime 先拒绝新 Run、取消并等待 active Run，再关闭 ExtensionSession。
5. MCP 初始化 task 必须先被入口取消/等待，或本身改由 supervisor 托管后再关闭 manager；不允许 connect 与 shutdown 无序并发。
6. cleanup error、task error 和 cancel timeout 都可观察；无 `Task exception was never retrieved`。
7. close 返回/抛出聚合错误后，Session 与 Runtime 都已经是 closed。

## Deferred Capabilities
- Command owner/handle/profile/Skill refresh：Stage 2C 独立设计。
- Observer/Interceptor、Hook Adapter 和事件顺序：Stage 2B。
- active phase 动态资源注册、session replacement、generation 切换：Stage 5 reload 前再开放。
- Python package/local path discovery、信任和配置：Stage 3/4。
- 将所有 App/Agent/Run 的裸 task 一次迁入 supervisor：不是 Stage 2A 目标。
- 强制杀死不响应取消的 Python task：做不到；只能超时、报告并避免无限阻塞关闭。

## Implementation Batches (Non-TDD)

### 2A0 - Freeze baseline and review seam
Files: no production changes; planning/status only.

Steps:
1. Confirm Stage 1 current branch, changed-file manifest and `669 passed` baseline.
2. Prefer a dedicated Stage 1 commit before Stage 2 coding; do not auto-commit without user authorization. If still uncommitted, record the exact manifest and keep Stage 2 diff separately auditable.
3. Re-read approved Stage 2A Interface and reject any Command/Event/reload scope creep.

Reason: current branch still contains uncommitted Stage 1 implementation plus pre-existing learning artifacts. A frozen baseline is required for meaningful rollback and attribution.

### 2A1 - Contracts, naming and ResourceScope core
Files:
- add `mewcode/extensions/resources.py`;
- modify `mewcode/extensions/contracts.py` and `mewcode/extensions/__init__.py`;
- after implementation, add `tests/test_extension_resources.py`.

Steps:
1. Add `RuntimeProfile` and keep `ToolProfile` as a compatibility alias.
2. Add `ExtensionTaskHandle`, `ExtensionCleanupFailure` and `ExtensionCloseError` contracts.
3. Implement ResourceScope and internal TaskSupervisor with named ledgers, category close ordering, cancel timeout and live diagnostic sink.
4. After the implementation exists, write Interface-level behavior tests for acquire/defer/task success, failure, timeout, reverse cleanup, concurrent/idempotent close and no un-retrieved task exception.

Reason: build the lifecycle Module independently before changing Host callers; tests come after implementation per the user's non-TDD requirement.

Exit gate: new resource tests pass; no Host or entry behavior has changed yet.

### 2A2 - Integrate ExtensionHost, ExtensionAPI and AgentRuntime
Files:
- `mewcode/extensions/host.py`;
- `mewcode/runtime/agent_runtime.py`;
- `mewcode/runtime/__init__.py` if exports change;
- after implementation, update `tests/test_extensions.py` and `tests/test_runtime_composition.py`.

Steps:
1. Replace per-extension raw AsyncExitStack with ResourceScope; keep one scope per definition and reverse extension close order.
2. Add `acquire/defer/start_task` to ExtensionAPI with the same activating-only phase guard as Tool registration.
3. Add a close lock/single close result to ExtensionSession; collect failures from every scope before raising one ExtensionCloseError.
4. Preserve original startup/cancellation exception while recording rollback cleanup failures.
5. Make AgentRuntime diagnostics live and keep Runtime closed even when Session close raises.
6. After implementation, extend tests for partial activation rollback, cancellation, cleanup aggregation, two Runtime isolation and realtime task diagnostics.

Reason: all activation/rollback/close callers cross the existing Host/Session seam; no entry should know ResourceScope internals.

Exit gate: Stage 1 ExtensionHost/Runtime tests plus Stage 2 resource tests pass.

### 2A3 - Add real built-in resource definition
Files:
- `mewcode/extensions/builtins.py`;
- `mewcode/extensions/contracts.py` only if typed binding aliases are needed;
- after implementation, update `tests/test_runtime_composition.py`.

Steps:
1. Extend BuiltinRuntimeBindings with optional pre-created `mcp_manager` and `stale_cleanup_factory`.
2. Add `mewcode.runtime-resources` as the catalog's second production ExtensionDefinition after built-in tools.
3. Register MCPManager shutdown through `defer`; start TUI stale cleanup through `start_task`.
4. Keep the definition a no-op for profiles without those bindings; do not start connections or change Tool profiles.
5. After implementation, test profile activation, owner diagnostics, task cancellation and reverse ordering through Host/Runtime Interface.

Reason: two real adapters prove ResourceScope is not hypothetical while keeping connection and worktree business logic outside Host.

Exit gate: real built-in Runtime opens/closes with no resource/task residue.

### 2A4 - Migrate entry ownership
Files:
- `mewcode/app.py`;
- `mewcode/remote.py`;
- `mewcode/__main__.py` external teammate path;
- potentially `mewcode/mcp/manager.py` only for small idempotency/diagnostic compatibility changes;
- after implementation, update `tests/test_tui_runtime_adapter.py`, `tests/test_remote_runtime_adapter.py`, `tests/test_teammate_registry.py` and `tests/test_mcp.py`.

Steps:
1. Construct MCPManager before AgentRuntime open, load configs, and pass it in typed bindings for TUI/Remote/external teammate.
2. Reuse that manager in existing async connect functions; never create an unowned local manager after Runtime activation.
3. TUI still cancels/awaits the App-owned MCP initialization task before Runtime close; ResourceScope then shuts down manager/clients and removes dynamic Tool Handles.
4. Remove direct manager shutdown from entry finally blocks and clear compatibility references after Runtime close.
5. Move TUI stale-cleanup coroutine creation into `stale_cleanup_factory`; remove `_stale_cleanup_task` cancellation fields/paths.
6. Preserve prompt behavior (no MCP/stale resource binding), Remote command behavior and teammate cancellation.
7. After implementation, verify provider switching, connect cancellation, shutdown order, exact-once close and no stale task/client.

Reason: ownership is established before fallible connection work, closing the current leak window where a local MCPManager can be lost if connect is cancelled before assignment.

Exit gate: four Runtime profiles and all migrated entry lifecycle tests pass.

### 2A5 - Hardening, deletion and full verification
Files: tests/docs plus deletion of obsolete entry cleanup code; no new capability.

Steps:
1. Remove unused raw AsyncExitStack wiring, direct MCP shutdown and stale task ownership paths made obsolete by ResourceScope.
2. Add post-implementation edge tests only where behavior is not already covered: swallowed cancellation timeout, simultaneous close, cleanup error after task error, and Runtime A close not affecting B.
3. Run Stage 2 target matrix, Stage 0/1 regression, full pytest, scoped Ruff, compileall, diff-check and structural searches.
4. Update detailed/main design with actual result counts and deviations.

Reason: deletion is part of the migration; leaving both ownership paths would create double close and unclear diagnostics.

Exit gate: no entry owns MCP shutdown or stale-cleanup task directly; all verification gates pass.

## Verification Strategy (Implementation After, Not TDD)
Development order for every batch:

1. Re-read approved Interface and relevant baseline behavior.
2. Implement the complete batch.
3. Review diff for scope and ownership errors.
4. Add or update tests for observable behavior through the public Interface.
5. Run the batch target tests; fix implementation or test only from observed mismatch.
6. Run cumulative Stage 0/1/2 regressions before starting the next batch.

There are no expected-failure/red-light steps and no red-green-refactor cycle.

Final target commands:

```bash
.venv/bin/pytest tests/test_extension_resources.py tests/test_extensions.py tests/test_runtime_composition.py tests/test_tui_runtime_adapter.py tests/test_remote_runtime_adapter.py tests/test_teammate_registry.py tests/test_mcp.py tests/test_agent_runtime.py tests/test_tool_pipeline.py tests/test_agent.py -q
.venv/bin/pytest -q
uvx ruff check --select E9,F63,F7,F82 mewcode tests
.venv/bin/python -m compileall -q mewcode tests
git diff --check
```

Structural gates:
- ExtensionAPI still has no Command/Event/reload methods.
- no migrated entry directly calls `MCPManager.shutdown()`;
- no TUI `_stale_cleanup_task` owner remains;
- ResourceScope is the only per-extension cleanup implementation;
- `asyncio.ensure_future()` in HookEngine remains explicitly deferred to 2B, not silently claimed as fixed.

## Expected File Impact
| File | Planned change | Why |
|------|----------------|-----|
| `mewcode/extensions/resources.py` | new deep Module | hide task/resource ownership, ordering, timeouts and cleanup diagnostics |
| `mewcode/extensions/contracts.py` | RuntimeProfile, task/error/diagnostic contracts | make lifecycle facts typed without leaking implementation |
| `mewcode/extensions/host.py` | API methods and ResourceScope integration | preserve one activation/rollback/close seam |
| `mewcode/extensions/builtins.py` | runtime-resources definition and typed bindings | connect two real production adapters |
| `mewcode/runtime/agent_runtime.py` | live diagnostics and close aggregation | make post-activation failures visible and closed state reliable |
| `mewcode/app.py` | MCP pre-ownership and stale task migration | remove TUI-owned resource cleanup |
| `mewcode/remote.py` | MCP pre-ownership | close connect-failure leak window |
| `mewcode/__main__.py` | teammate MCP pre-ownership | unify external teammate close semantics |
| `mewcode/mcp/manager.py` | only minimal compatibility if required | keep Tool handles/connection implementation in existing Adapter |
| `tests/test_extension_resources.py` | post-implementation Interface verification | test depth through ExtensionAPI/Session, not private ledgers |
| existing Runtime/entry tests | post-implementation regression updates | verify real adapters and compatibility |

No change is planned for CommandRegistry, HookEngine, configuration schemas, Session JSONL or the learning artifacts.

## Design Validation Result
- 详细设计覆盖了范围选择、删除测试、外部 Interface、内部 Module、状态与并发不变量、失败/取消/超时、两个真实 Adapter、2A0-2A5 步骤、文件理由和实现后验证矩阵。
- 主路线已把原 2A 拆成资源/任务 2A、事件 2B、Command ownership 2C，Stage 1 历史文档的后续阶段表同步更新。
- 三份设计文档的相对链接和代码/Mermaid 围栏通过校验，无行尾空白；`git diff --check` 通过。
- active plan 指向 `2026-08-16-mewcode-extensionhost-stage-2-design`。
- 本轮没有修改 `mewcode/` 生产代码或测试代码；工作区中的这些修改仍是此前未提交的 Stage 1 实现。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Stage 2 范围以主路线与当前源码共同决定 | 文档可能是终局方向，真实调用与所有权必须以当前仓库校验 |
| 实施流程采用 design-first, verify-after | 尊重不用 TDD 的要求，同时保留行为基线、自动化验证和回归门 |
| Interface 测试仍是主要测试面 | 不采用 TDD 只改变开发顺序，不改变深 Module 的可验证性要求 |
| 优先把“扩展资源/扩展任务”与“产品后台 Agent 任务”分开 | 两者生命周期、可见性和失败语义不同，混用会形成浅而危险的 Task Interface |
| 不把 `CommandContext` 作为 ExtensionHost 的外部 Interface | 它是入口执行上下文，不是扩展激活上下文；两者混合会把 TUI/Remote 细节泄漏进 Host |
| ResourceScope 深化现有 per-extension `AsyncExitStack` | 复用已验证的事务与反向清理 seam，删除该 Module 会让复杂度重新散回 Host/API，具备实际 Depth |
| TaskSupervisor 只定义“扩展协程所有权” | 先解决明确 owner 的任务；产品级 App/Run/Agent 后台任务另有生命周期，不在此 Interface 中伪装统一 |
| Stage 2 候选优先资源与受控任务，不优先 Command | 它们可直接深化现有 per-extension scope，且有 MCP/stale-cleanup 两个真实 Adapter；Command 还牵涉入口 profile 与执行 Context |
| Stage 2A = ResourceScope + TaskSupervisor | 这是对 Stage 1 seam 的纵向深化，能够独立交付并为 2B EventPipeline 提供任务所有权地基 |
| Command 从原 2A 拆到后续 2C | 避免把资源生命周期和交互命令语义绑成一个不可独立回滚的批次 |
| cleanup 失败聚合后抛出，状态仍 closed | 既不静默吞错，也不因首个错误跳过剩余清理 |
| ResourceScope 分类关闭而非单一裸 ExitStack | capability、task、resource 有安全顺序要求；分类账本让这条不变量集中在一个 Implementation |
| task 失败默认 degraded，不自动关闭 Runtime | 后台失败发生在 open_session 返回后，自动关闭需要额外 supervisor-to-runtime 控制面，留到有真实需求再设计 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 暂无 | - |

## Pi 官方源码复核（优先于二手文章）

### 已确认的事实

- `packages/agent/src/agent-loop.ts` 中的 `runAgentLoop()` 会为一次运行复制当前 Context 的消息列表，并在循环内发出 `agent_start`、`turn_start` 等生命周期事件；这支持“Run 使用快照、Loop 在快照上推进”的判断。
- `packages/agent/src/agent.ts` 把 steering 与 follow-up 建模为两个 `PendingMessageQueue`，并分别提供 enqueue、drain、clear；它们不是同一种输入的两个名字。
- `packages/agent/docs/harness-v2.md` 提出的稳定拆分不是更多大而全的回调，而是两个无持久状态的 building block：`streamAssistant` 与 `executeToolBatch`；现有 `agentLoop` 只保留为薄组合层，上层 harness 可在阶段之间插入持久化或调度。
- 官方 usage 文档确认：steering 在当前 assistant turn 的工具执行结束后送入；follow-up 在当前工作完全结束后送入；abort 会恢复队列中的消息。这些是面向用户可观察的不同语义。
- `harness-v2.md` 明确 Tool batch 的准备/通知保持顺序、实际执行可并行、最终结果与事件恢复源码顺序；这与 MewCode 现有 `ToolPipeline` 很可能是直接可比的模块边界。

### 文章与当前官方设计的差异

- 文章将 `stopReason=length` 后仍可能执行本轮 ToolCall 作为教学路径描述；当前 `harness-v2.md` 则规定 length 时所有 ToolCall 失败且不执行。后续设计以当前官方源码/设计为准，不把文章例子当成稳定契约。
- 文章的 callback overlay 适合解释概念；官方 harness 设计更强调阶段积木和薄编排器。对 MewCode 的借鉴应优先形成清晰阶段 seam，避免把 `AgentLoop` 变成 callback 配置集合。

### 对下一阶段的当前推论（待源码对照）

- ResourceScope 解决的是扩展运行时的资源所有权，价值明确但偏运维基础设施；新材料指向一个更直接的产品功能缺口：运行中的输入队列、Turn 后停止决策、下一 Turn 的 Context/模型变换。
- 不应重写第二套 Loop。候选方向应是深化 Stage 0：让现有 `AgentLoop` 保持薄编排，把已有 Model streaming 与 Tool batch seam 明确化，并增加最小的 Run 控制面。
- 下一步需要判断 MewCode 当前是否已经具备上述 seam；只有确认 Context、stop policy、queued input 或 phase mutation 仍散落后，才调整 Stage 2 优先级。

## MewCode Agent Loop 第一轮对照

- Stage 0 已经建立唯一的 `AgentLoop` 和独立 `ToolPipeline`，并由 `AgentRun` 负责 cancel -> settle -> idle。这里已有很好的内核边界，不需要复制 Pi 的循环。
- `ToolPipeline` 已处理截断 ToolCall、准备/校验、权限、pre/post hook、并行安全分组、结果持久化与 terminate；它实际上已经承担 Pi `executeToolBatch` 的大部分职责。
- `AgentEvent` 已覆盖 run/turn/message/tool/usage/compaction 生命周期，说明下一阶段不必先发明另一套事件词汇。
- `Agent.start_run()` 在已有 active run 时直接拒绝，当前没有看到 steering/follow-up 队列；TUI/Remote 主要暴露 cancel。因此“运行中追加意图”是一个真实且用户可感知的能力缺口。
- `RunRequest` 目前直接持有可变的 `ConversationManager`，尚未看到明确的 Run Context snapshot contract。需要继续确认主循环何时读取、注入与压缩 conversation，不能仅凭类型断定存在竞态。
- 当前并行 Tool 的最终 message 会按 source index 排序，但执行完成事件在 completion queue 取出时立即发出，可能是完成顺序而非源码顺序。是否调整必须先确认 UI 与现有测试契约，不能直接照搬 Pi。
- 因 `ToolPipeline` 已经是深 Module，候选下一模块不应叫泛化的 `executeToolBatch`；更可能是围绕现有 Loop 的 `RunInbox` 与 typed turn decision，并让编排器继续保持薄。

## MewCode Agent Loop 详细对照

### 已有能力与可保留边界

- `AgentLoop._run_loop()` 已完整表达 model -> tool -> model：无 ToolCall 时自然结束，有 ToolCall 时统一进入 `ToolPipeline`，工具要求 terminate 时结束，超过 `max_iterations` 时硬停。
- 截断响应会进入 `_record_truncated_response()`；其中 ToolCall 虽传给 `ToolPipeline`，但 pipeline 的 `is_truncated` gate 会生成错误结果而不真正执行。实际行为与当前 Pi harness 设计一致。
- `ToolPipeline` 返回的 conversation messages 按 source index 排序，模型看到的 ToolResult 顺序稳定；这是必须保留的核心契约。
- `AgentRun.wait_until_idle()` 比单纯的 `LoopComplete`/`RunFinished` 更接近真正的 settled boundary，应继续作为切换 run 或关闭 runtime 的安全点。

### 当前散落在 Loop 内的 Turn 准备职责

每轮模型调用前，`AgentLoop` 依次直接完成 mailbox 消费、notification 注入、pre-send hook、system prompt、plan/coordinator reminder、hook notification、deferred-tool reminder、auto compact、环境/长期记忆再注入、tool schema 投影。这说明真正变厚的不是 Tool batch，而是“下一 Turn 如何准备”。

这与 Pi `prepareNextTurn` 的思想相符，但不宜照搬为任意 callback。更深的 MewCode Module 候选是 typed `TurnPreparer`/`ContextProjector`：集中回答下一次模型调用的 messages、system、tools 以及准备时产生的 events，同时保留 Conversation 的持久历史所有权。

### 真实入口行为不一致

- TUI 在 streaming 期间收到普通输入，会取消当前 `_agent_task`，等待取消完成，显示 interrupted，再把新输入启动成一个新 run。
- Remote 在 `_streaming` 时直接丢弃新 `user_message`。
- Agent 核心在 active run 存在时拒绝第二个 `start_run()`。

所以当前系统对“运行中用户又说了一句话”有三种语义：打断重启、静默丢弃、抛错。这个不一致比 ResourceScope 更直接影响产品行为，也正是 steering/follow-up 队列可以解决的问题。

### 生命周期与策略缝隙

- 自然结束路径执行 `turn_end` hook 后直接发 `LoopComplete`，没有 `TurnComplete`；工具路径才发 `TurnComplete`。若要在 turn boundary 注入 steering，这个事件/阶段不对称必须先统一。
- `batch.terminate` 当前使用“任一 ToolResult terminate 即停”，Pi 当前 harness 文档描述的是“全部 finalized result terminate 才停”。这不是可机械借鉴的点；MewCode 现有语义可能与工具业务有关，改动前必须单独决策。
- `AgentLoop` 直接持有并修改外部传入的 `ConversationManager`。入口当前基本在 run 前加用户消息，但核心 contract 没有阻止 run 中的外部 mutation。下一阶段应定义 single-writer/queue 规则，而不是复制整个历史形成脱离 Session 的深拷贝。
- `_finish_natural_turn()` 用裸 `asyncio.create_task()` 启动 memory extraction/consolidation；这属于 Agent 运行期后台任务，不是 extension installer task，进一步证明原 ResourceScope 不能顺手声称统一所有异步任务。

### 优先级信号

现在已有足够源码证据把“Run 控制面 + Turn 准备 seam”列为比 ResourceScope 更值得优先交付的功能切片：它统一三入口语义，并从现有肥 Loop 中抽出真实复杂度。ResourceScope 仍保留，但可以顺延到后续独立批次。

## Pi 官方 Loop 的精确边界（用于约束借鉴范围）

- `shouldStopAfterTurn` 在本 Turn 完成后、再次拉取 steering 前执行；它是硬策略点，不等于“模型没发 ToolCall”的自然停止。
- steering 维持 inner loop；follow-up 只在 inner loop 原本要停止时检查，并把消息重新放回 pending 后开启下一轮。这解释了为什么必须有两个队列，而不是一个带模糊优先级的通用 inbox。
- `transformContext` 与 `convertToLlm` 都位于真正模型调用的 seam；MewCode 可借鉴这个位置，但不需要复制 `AgentMessage` 类型体系，因为现有 `ConversationManager` 已是内部消息模型。
- Pi 对 streaming partial assistant message 使用“先放占位、后原位替换”；MewCode 当前用 `StreamCollector` 完成后一次回写 Conversation。只要取消与持久化契约没有要求保存 partial，这不是当前阶段需要照搬的功能。
- 官方 truncated 分支明确把所有 ToolCall 转成错误结果且不执行，MewCode 当前行为已经一致，因此不列入下一阶段改动。

## Revised Next Stage Decision

### Selected vertical slice

Stage 2A 改为 `AgentRun Control Plane`：

- 内部深 Module：`RunControl`，拥有 steering/follow-up 双 FIFO、投递优先级、hard-stop seal、exactly-once 与 undelivered recovery；
- 外部 Interface：`AgentRun.steer()`、`AgentRun.follow_up()`，以及 AgentRuntime 的 active-run 窄 facade；
- Core Adapter：AgentLoop 只在首次模型调用前和每个完整 Turn 后读取 typed directive；
- Product Adapter：TUI Enter/Alt+Enter/Escape 与 Remote `delivery`/ack；
- 生命周期修正：每个完整模型 Turn 恰好一次 `TurnComplete`，`session_end` 只在真正 Run 停止时触发。

### Explicitly deferred

- `TurnPreparer` 作为 2B 单独设计门：它有真实 Depth，但会同时触及 compaction、memory、Hook、mode reminder 和 Tool projection，不与输入控制同批实施。
- ResourceScope + TaskSupervisor 的原详细设计保留并顺延为候选 2C；它解决扩展资源所有权，不解决现有入口的运行中输入冲突。
- EventPipeline 与 Command ownership 相应顺延，仍需独立审批。

### Compatibility decisions

- 单 active run 保持不变；queue 是同一 Run 内的控制输入，不是第二个 Run。
- 第一版固定 drain-all，不新增配置 schema。
- `ToolResult.terminate` 保持 MewCode 当前 any-result 终止语义，不机械改成 Pi 的当前规则。
- 不深拷贝 Conversation；以 AgentLoop single-writer 规则防止 active run 中的外部 mutation。
- queued input 不跨进程持久化；本阶段只保证正常停止/取消时通过 RunResult 恢复未投递内容。

## Stage 2A Implementation Authorization

- 用户已明确要求开始并持续到完成；此前“只设计、不修改生产代码”的审批门已解除。
- 开发仍遵守已确认的非 TDD 流程：先实现完整批次，再补/改可观察行为测试和回归。
- 当前脏工作树中的 Stage 1 实现与用户学习材料必须保留；Stage 2A 只在设计列出的重叠文件上做增量修改。

## 2A0 Baseline Evidence

- 当前分支为 `codex/mewcode-extensionhost-stage-1`，HEAD `6578fa6`；Stage 1 生产/测试修改仍未提交。
- Stage 2A 必须在已有 `app.py`、`remote.py`、`runtime/__init__.py` 与 untracked `agent_runtime.py` 上增量编辑，不能用 HEAD 内容覆盖这些 Stage 1 变化。
- 用户学习材料 `docs/plugin-agent-learning-design.md`、`docs/cordis-python-async-learning-guide.md`、`examples/`、`tests/test_mini_pi_agent.py` 继续保持非产品范围。
- 开发前目标基线：AgentRun、ToolPipeline、Runtime composition、TUI/Remote Adapter 与 Agent 共 `52 passed`；`git diff --check` 通过。

### Current core implementation constraints

- `RunFinished` 由 `AgentLoop.run()` 在返回给 `AgentRun._drive()` 前发出，因此正常/失败/取消路径必须在构造该 RunResult 前 seal RunControl；AgentRun 的 fallback settlement 仍需补 undelivered，但不能依赖它修正已经发出的事件。
- `StreamingEventAdapter.emit()` 会等待消费者 acknowledge，queued ack 不能从 enqueue 路径复用 EventSink，否则用户输入会被当前事件消费反压；delivery event 应继续走串行 EventSink。
- `TurnComplete` 当前只在 Tool batch 路径发出；自然路径在 `_finish_natural_turn()` 同时执行 `turn_end` 与 `session_end` 后直接 LoopComplete。2A2 必须拆开“Turn 收尾”和“Run 真正结束”。
- `max_iterations` 当前在下一轮开头判断；2A2 若在边界提前判断，必须保留“自然结束且无 queued input 仍 completed”的现有语义。
- `AgentRuntime` 已是 TUI/Remote 组合根 facade，新增 active-run queue 方法可以保持入口不读取 RunControl 私有状态。
- `mewcode.runtime.__init__` 是稳定导出面；新合同和错误需要在核心实现稳定后显式导出，不能让入口从私有模块导入。

### Current adapter and persistence constraints

- `ChatInput.Submitted` 当前只有 text；Alt+Enter 最小兼容改法是让提交事件携带 delivery kind，而不是在 App 层猜按键来源。
- TUI `_send_message()` 在新 Run 前把首条用户消息同时写 Conversation 与 Session，然后把 `history_cursor` 放到其后；active-run queued input 必须只渲染/ack，不能走这段直接写路径。
- TUI 的 `TurnComplete` 消费者无条件创建下一 AI row；新增自然 TurnComplete 后必须读取 `will_continue`，否则每个正常结束都会留下空回复区。
- TUI 当前只在 TurnComplete/LoopComplete flush history；RunFinished/cancel 需要补最终 tail flush，才能保存已 delivered 但下一 Turn 未完成的 queued input 和 paired cancel ToolResult。
- `MewCodeApp.send_user_message()` 与 `_dispatch_command()` 也会在 streaming 时丢普通消息；需区分是否属于用户可见 active input，避免只修键盘路径仍留下旁路。
- Remote WebSocket 当前只传 content，active `_handle_user_message()` 直接 return；协议需要把可选 delivery 一路传入 handler，并以 receipt 产生 queued ack。
- TUI/Remote 生产运行都已有 `self.runtime`，可通过 AgentRuntime facade 排队；它们无需导入 RunControl。
- 当前 TUI/Remote Adapter 测试主要覆盖 Runtime 装配/关闭，没有运行中输入行为，2A4 实现后需要真实新增验证。

## 2A1 Implementation Result

- 新增 `mewcode/runtime/run_control.py`，公开 Interface 只有 enqueue、before-first-turn、after-turn、seal、recover 和只读状态/数量。
- 两类队列内部用独立 deque 保证同类 FIFO，并用内部 sequence 在 hard stop 恢复时还原跨类型的真实 enqueue 顺序。
- `after_turn()` 集中 steering 优先、Tool/retry continuation、natural follow-up、max-turn 条件和 hard stop，不依赖 Conversation、EventSink、Agent 或 UI。
- seal 与队列空判断均为无 await 同步方法；sealed 后 enqueue 明确抛 `RunInputClosedError`，不存在 accepted-but-never-consumed 状态。
- 实现后新增 11 个 Interface 测试；RunControl + Stage 0/1 目标回归共 `63 passed`，Ruff/compileall/diff-check 通过。

## 2A2 Integration Review

- `AgentLoop` 的 `RunResult` 构造点都位于同一实现文件，新增 `undelivered_inputs` 默认值不会破坏既有调用者；正常 Loop 路径仍必须在 `RunFinished` 发出前完成 seal/recover。
- 旧测试把 `TurnComplete` 当成“工具批次完成”事件，因此自然回答新增同名事件会让两个数量断言失败；这不是兼容性 bug，而是详细设计已经批准的“每个完整模型 Turn 恰好一次”合同变化，测试需要改为验证 turn/reason/will_continue。
- legacy `Agent.run()`、CLI、sub-agent 和 memory consolidation 都通过同一个 `AgentLoop`，不需要另建控制分支；没有持有 `AgentRun` 的消费者仍保持原 async iterator 行为。
- `StreamingEventAdapter` 只需要识别 `RunFinished` 来结束；新增 `RunInputDelivered` 和更完整的 `TurnComplete` 会透明通过，实际 UI/Remote 消费者必须显式处理或安全忽略。
- 每次 `Agent.start_run()` 都新建独立 `AgentLoop`，所以 Loop 内的 turn、last_text 和 session-started 状态不会在并发 Run 间共享；RunControl 放在 AgentRun 内与现有单 active-run 约束一致。
- 首轮前只投递 steering，follow-up 保留到自然停止边界；Turn 后事件顺序固定为 `TurnComplete -> RunInputDelivered -> next TurnStarted`，既能给 Adapter 准确 ack，也避免 active 输入旁路修改 Conversation。
- 当前 `session_end` 已从自然 Turn helper 移到 Run wrapper，因而 tool terminate、max-turn、cancel 和 failed 都会在 session 真正停止时执行；后续行为测试应验证 exactly once，而不是依赖 UI 事件数量间接推断。

## 2A3 Runtime Facade Review

- AgentRuntime 已经是两个产品入口持有的组合根，facade 只需转发到当前 AgentRun；没有 active run 时返回 `None`，让 Adapter 保留启动新 Run 的所有权。
- Runtime 的 `closing/closed` 状态必须对 start、queue 和 cancel 使用同一拒绝规则；否则 close 已开始后仍可能接受一个永远不会被 Loop 消费的输入。
- sealed/settling race 不应由 facade 吞掉：`RunInputClosedError` 继续交给 Adapter，Adapter 才知道应等待 idle 后按入口语义启动新 Run。

## 2A4 Adapter Entry Points

- TUI 的键盘提交集中在 `ChatInput.Submitted -> on_chat_input_submitted -> _dispatch_command/_send_message`，但程序化 `send_user_message()` 和 command 回退也能启动任务；active 输入迁移必须覆盖这三个入口，不能只改键绑定。
- 当前 active TUI 提交明确 cancel `_agent_task` 后重启；Remote WebSocket 则在 `_streaming` 为 true 时直接 return。两条正是 Stage 2A 要删除的冲突路径。
- Remote 消息解析目前只转发 content；要支持 follow-up，`delivery` 必须从 WebSocket payload 传到 handler。Core event handler 已集中处理 Turn/Loop 等事件，适合在那里增加 delivered/restored ack。
- 两入口虽然通过 legacy `agent.run()` 消费事件，但运行本身仍由 AgentRun 创建，因此 `runtime.steer_active_run()` 可以直接找到同一个 active run；无需把整个渲染循环改写成显式 `runtime.start_run()`。
- TUI cancel 当前同时调用 `agent.cancel_active_run()` 和取消外层 `_agent_task`，后者可能让 Adapter 来不及消费 `RunFinished`；为了可靠 flush/restore，应让 AgentRun 先完成并只在没有 active run 时才取消外层任务。
- queued 输入不能复用 `_send_message()` 的首消息路径，因为该路径会立即写 Conversation 与 Session；Adapter 需要单独渲染 queued 状态，收到 `RunInputDelivered` 后更新同一个 UI 元素，Conversation 仍只由 AgentLoop 写入。
- TUI 当前每个 `TurnComplete` 都无条件创建下一 AI row；自然 Turn 现在也发该事件，因此必须仅在 `will_continue=True` 时创建新 row，最终自然 Turn 复用当前 row 收尾。
- TUI 的 Session 游标在首条消息落盘后建立，TurnComplete 会 flush delivered queued input；仍需在 `RunFinished` 再 flush 一次，覆盖取消期间新增的 paired ToolResult 或已投递但未完成下一 Turn 的 tail。
- Remote 当前没有把 Conversation 写入 Session，2A 先保持其既有持久化边界；但 queued/delivered/restored 三类 ack 可以完全从 receipt、`RunInputDelivered` 和 `RunFinished.result.undelivered_inputs` 得到。
- Adapter 实现后的单元行为已证明：TUI active queue 不直接改变 Conversation；Remote sealed race 会等待旧 Run idle 后把原文作为新 Run 首消息，而不是返回成功后丢弃。
- 剩余 `_agent_task.cancel()` 只位于 TUI Escape 的“没有 active AgentRun”fallback 与应用 shutdown；active 普通提交路径已不再 cancel，属于允许保留的生命周期清理。
- 进一步定位发现第二处并非 shutdown，而是 `action_handle_ctrl_c` 的 active streaming 分支；它同样会截断 RunFinished，必须与 Escape 一样先调用 Runtime 协作式 cancel，只有没有 active run 才 cancel 外层 task。

## 2A5 Persistence Audit

- Session 可以通过 `meta.message_count` 与其 JSONL 路径验证 exactly-once；TUI vertical test 可使用真实 AgentRuntime 和 gated LLM，不必伪造 RunFinished。
- `history_cursor` 在 `_send_message()` 中于 AgentRun 启动前按 list index 建立，但 AgentLoop 首轮会把 environment/long-term memory 插到 history 前部；这可能把 cursor 指向的对象整体右移，导致首条用户消息被 TurnComplete 再次 flush。2A5 必须用对象/稳定边界或启动后 cursor 修正消除重复，而不能只增加 RunFinished flush。
- Ctrl-C 修复后 active cancellation 会继续消费 RunFinished；这样 cancelled ToolResult 与 undelivered recovery 才能到达 TUI，外层 task fallback 只处理核心 Run 尚未建立的窗口。
- 结构搜索后仅剩两处入口 `add_user_message()`，都在启动新 Run 的 idle 路径；active queued input 没有 Conversation 旁路写入。
- TUI 两处 `_agent_task.cancel()` 现在都位于 Runtime 报告“没有 active run”之后的 fallback；普通提交路径完全无 cancel。Remote 已删除 `_cancel_event` 与 event-loop early break。
- Remote cancel 在 Runtime closing/closed 时仍可能收到 WebSocket 消息；由于 facade 明确拒绝非 active 状态，Adapter 应捕获 RuntimeError 并保持 shutdown 幂等，不能让连接处理协程异常退出。

## Final Audit Evidence

- 全量 pytest 为 `693 passed, 1 skipped, 1` 个既有 unknown-timeout-mark warning；Stage 2A 目标矩阵为 `76 passed`。
- 生产结构仍只有一个 `AgentLoop`、一个 `ToolPipeline` 和一个独立 `RunControl`；RunControl 文件没有 TUI、Remote、Conversation、client 或 ExtensionHost import。
- 当前 git status 同时包含未提交 Stage 1 与用户学习材料；最终交付必须明确“不提交、不覆盖”，不能把全工作树 diff 都宣称为本阶段新建。
- 两份主设计文档的状态栏、审批门和“当前结果”仍写着等待授权/未实施；实现完成前必须同步为真实结果、测试计数、持久化 anchor 偏差和顺延阶段，避免文档与代码相反。
- 文档同步后仅剩“用户明确授权后才开始修改”的已勾选审批事实，不再存在“尚未实施/等待授权/本轮未改生产代码”的过期状态描述。
- `planning-with-files` 提供 `check-complete.sh`、`plan-doctor.sh` 与 attest 脚本；最终应使用技能自带 completion gate，而不是只手工数 checkbox。
- completion script 只根据 `### Phase` 与 Status 统计；应在最后一轮验证和文档同步确实完成后再把 Phase 15 标为 complete，然后运行它确认 15/15，而不是为了让 gate 变绿提前改状态。
- `check` 技能把本任务归为 Plan Execution，而非普通 PR review：应核对工作树漂移、执行项目验证，然后给 completion ledger；不需要为了形式制造 review finding。
- 当前树是未提交 Stage 1 前置实现加 Stage 2A 增量，clean HEAD 单独无法运行 2A；最终可信验证应在临时 detached worktree 中应用 tracked diff，并只复制 Stage 1/2A 所需的 untracked 产品与测试文件，排除用户学习 artifacts。
- 当前 review preflight：分支 `codex/mewcode-extensionhost-stage-1`，HEAD `6578fa6c5394dc2ef0ce6c260241f9ba623f279c`；dirty/untracked 状态与规划记录一致，没有出现未知 commit 或分支漂移。
- `pyproject.toml` 只声明 pytest/pytest-asyncio dev 依赖，没有项目专用脚本或 pytest 配置；最终沿用已经实际运行的 `.venv/bin/pytest -q` 与显式 Ruff/compileall 门。
- 临时 detached worktree 从 `6578fa6` 重放 tracked diff，并只复制 Stage 1+2A 所需 untracked 产品/测试文件；目标 `76 passed`、隔离全量 `687 passed, 1 skipped, 1 warning`、Ruff/compileall/diff-check 通过。当前工作树全量的 693 与隔离 687 差 6 个，来自刻意排除的用户 Mini Pi 学习测试。
- `check` Plan Execution 审计未发现目标漂移或 release hard stop；没有依赖、配置、Session schema、ToolPipeline 或 destructive/public action 变化，且未执行 commit/push。

## Resources
- `docs/mewcode-pi-inspired-runtime-design.md`
- `docs/mewcode-extension-host-stage1-design.md`
- `.planning/2026-08-16-mewcode-extensionhost-stage-1-design/`
- `mewcode/extensions/`
- `mewcode/runtime/agent_runtime.py`
- `https://dg-ai-notes.pages.dev/modules/ch03-agent-loop/`（外部二手讲解，fetch tier=local；作为文章观点引用）
- `https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts`（Pi 官方源码）
- `https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent.ts`（Pi 官方 Agent 与输入队列）
- `https://github.com/earendil-works/pi/blob/main/packages/agent/docs/harness-v2.md`（Pi 官方阶段积木设计）
- `https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md`（Pi 官方交互语义）

## Stage 2B TurnPreparer Implementation Evidence

- `AgentLoop._run_loop()` 原本在每次模型调用前直接处理 mailbox、notification、pre-send Hook、system prompt、plan/coordinator reminder、Hook notification、deferred-tool reminder、auto compact、memory/environment 重注入和 Tool Schema 投影。
- 新增 `mewcode/runtime/turn_preparer.py`，其内部 Interface 只有 `prepare(conversation, turn, emit, cancellation) -> PreparedModelCall`；返回值只包含 system prompt 与不可变 Tool Schema tuple。
- TurnPreparer 明确不拥有 TurnStarted/TurnComplete、模型 streaming、ToolPipeline、RunControl、session start/end 或 max-turn/terminate 决策。这些职责仍保留在既有深 Module 中。
- HookEngine 与 HookContext 原本由 Agent 拥有，因此 Hook 调度实现移动到 `Agent._run_hook()`；AgentLoop 和 TurnPreparer 直接复用，删除了 AgentLoop 的浅转发方法。
- auto-compact 仍先读取一次 Tool Schema 用于摘要，再在压缩可能改变可见工具后重新投影本轮 Tool Schema；顺序与原实现一致。
- 实现后新增两个 TurnPreparer Interface 测试：普通准备投影、压缩后的 environment/memory 重注入与 CompactNotification。
- 新增真实慢 Tool batch 纵向测试：Tool 执行期间入队 steering/follow-up，完整 ToolResult 先写回，steering 才进入下一模型调用，follow-up 继续等到自然停止点。
- 相关目标回归为 `42 passed`；完整工作树为 `696 passed, 1 skipped, 1` 个既有 unknown-timeout-mark warning；compileall 和 `git diff --check` 通过。
- 当前受限运行环境不能访问默认 uv cache，仓库 `.venv` 也未安装 Ruff；因此本阶段不声称 Ruff 通过，验证改用现有 `.venv/bin/python`。
