# Progress Log

## Session: 2026-08-16 - Stage 2 design start

### Current Status
- **Phase:** complete - Stage 2A design, implementation not started
- **Started:** 2026-08-16

### Actions Taken
- 恢复并阅读已完成的 Stage 1 计划、发现、进度和最终验证结论。
- 读取 `planning-with-files`、`codebase-design` 和 deepening 依赖分类准则。
- 创建独立计划 `.planning/2026-08-16-mewcode-extensionhost-stage-2-design/` 并切换 active plan。
- 固定本轮不修改生产代码，以及未来开发不使用 TDD、改为实现后验证的约束。
- 从主路线确认 Stage 2A/2B 原始拆分，并识别 Stage 1 完成后的新审批门。
- 初步盘点 Command、ExtensionHost、MCP、Hook 和异步任务符号；确认产品后台 Agent 任务与扩展后台协程必须分开建模。
- 完成 Command 注册与调用路径第一轮跟踪：确认冲突已有、所有权/注销缺失，且 TUI/Remote 的 Command profile 和运行期依赖明显不同。
- 跟踪 ExtensionSession/AgentRuntime/MCP 的关闭 seam：确认 per-extension AsyncExitStack 可直接深化为 ResourceScope，但 MCP 的运行期连接暂不适合强行迁入激活期 API。
- 区分四类异步任务 owner；确认 Stage 2A 的 TaskSupervisor 应只管理 extension installer 创建的协程，HookEngine 的未跟踪任务留作 Stage 2B 真实接入点。
- 复核现有测试与 TUI/Remote 关闭代码，完成 Command、资源、任务、Hook/MCP 的依赖分类和 owner 矩阵。
- 识别 ResourceScope/TaskSupervisor 的两个真实 tracer bullet：MCPManager async cleanup 与 TUI worktree stale-cleanup task。
- 完成三候选切片比较，确定 Stage 2A 只做 ResourceScope + TaskSupervisor；EventPipeline 保持 2B，Command 所有权拆为后续 2C。
- 初步冻结 ExtensionAPI 的 `acquire/defer/start_task` 三方法 Interface、关闭顺序、取消超时、聚合错误和实时 diagnostics 语义。
- 完成 ResourceScope、TaskSupervisor、聚合关闭错误、实时 diagnostics、built-in runtime-resources Adapter 和并发关闭不变量设计。
- 明确 Stage 2A 推迟 Command/Event/reload/discovery，也不承诺强制杀死吞取消的 Python task。
- 拆出 2A0-2A5 六个非 TDD 实施批次，逐批固定文件、步骤、理由、退出门和回滚边界。
- 定义“实现完整批次后补 Interface 测试”的验证流程及最终目标/全量/static/结构命令。
- 工作区审计确认 Stage 1 仍未提交，Stage 2 开发前应先冻结基线；本轮不会自行提交。
- 创建 `docs/mewcode-extension-resources-stage2a-design.md`，完整记录 ResourceScope/TaskSupervisor Interface、生命周期、Adapter、2A0-2A5 与非 TDD 验证矩阵。
- 主路线升级到 v0.6：2A=资源/任务、2B=事件、2C=Command contribution；Stage 1 后续阶段表同步。
- 相对链接、代码/Mermaid 围栏、行尾空白、`git diff --check` 和 active-plan 指针校验通过。
- 设计阶段完成；未修改生产/测试代码，等待单独开发授权。

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Stage 1 prerequisite | Stage 1 已完成并可作为 Stage 2 基线 | `669 passed, 1 skipped, 1 pre-existing warning` | passed |
| Design links/fences | 三份设计文档相对链接存在、围栏平衡 | passed | passed |
| Markdown whitespace | 新设计与 planning 无行尾空白 | no matches | passed |
| Git diff check | tracked design diff 无 whitespace error | exit 0 | passed |

### Errors
| Error | Resolution |
|-------|------------|
| Markdown fence 校验命令把反引号放入 shell 双引号，zsh 将其解释为命令替换并报 `unmatched` | 不涉及文件写入；改用单引号保护正则后重新执行校验 |

## Session: 2026-08-16 - Agent Loop material re-evaluation

### Current Status
- **Phase:** complete - revised Stage 2A design, implementation not started

### Actions Taken
- 根据用户提供的新文章重新打开已完成的 Stage 2 计划，不把 ResourceScope 结论视为不可修改。
- 读取 `read`、`planning-with-files`、`codebase-design` 与 deepening 指南。
- 固定外部页面只写入 findings、区分来源事实与项目推论的研究边界。
- 通过本地 extractor 成功读取 Agent Loop 正文，提炼 Trace/Turn、最小 Loop、停止规则、steering/followUp、prepareNextTurn、context snapshot、消息转换和 Tool batch 分层。
- 初步判断文章的主要价值是“Loop 内核 + 可移除控制叠加层”，需要对照 MewCode Stage 0，而不是直接替换已统一的 AgentLoop。
- 用 Pi 官方 `agent-loop.ts`、`agent.ts`、`harness-v2.md` 和 usage 文档复核二手文章；确认 Context snapshot、双输入队列、阶段积木和 Tool batch 顺序语义。
- 发现文章与当前官方 harness 在 `stopReason=length` 后是否执行 ToolCall 上存在差异；后续以官方当前设计为准。
- 把候选方向从“直接继续 ResourceScope”扩展为“ResourceScope 与 Run 控制面/Loop 阶段 seam 的优先级比较”，尚未作最终改序。
- 完成 MewCode Loop/ToolPipeline/Agent 第一轮符号与实现对照：确认 Tool batch 已经是深 Module、run settlement 已存在、事件词汇已较完整。
- 初步确认 active run 当前只支持拒绝第二个 run 或 cancel，未见 steering/follow-up 队列；把 Run 中追加输入列为真实候选功能。
- 记录 Conversation 是可变引用而非显式 snapshot，以及并行 Tool 事件可能按完成顺序发出；两点都需继续查明真实调用与测试契约。
- 完成主循环逐段阅读：确认 ToolPipeline 已匹配当前 Pi 的截断不执行规则，且 conversation 中的 ToolResult 按 source order 稳定。
- 识别 Loop 真正过厚的位置是每轮 Context 准备：mailbox、notification、hook、模式 reminder、compaction、memory/environment 与 tool projection 全部集中在 `_run_loop()`。
- 追踪 TUI/Remote/Agent 三入口：运行中普通输入分别表现为取消重启、静默丢弃、拒绝并发，形成明确的产品行为不一致。
- 发现自然结束路径缺少 `TurnComplete`，以及 Agent 运行期 memory/consolidation 后台任务仍由裸 `create_task()` 创建；两点纳入后续边界设计。
- 当前倾向把“Run 控制面 + Turn 准备 seam”提前为下一功能阶段，ResourceScope 顺延，但最终名称、Interface 和批次仍待设计。
- 进一步核对 Pi 官方 loop：确认 steering 维持 inner loop、follow-up 只在自然停止点重启、stop policy 先于下一批 steering；同时确认 Context transform 只位于模型调用 seam。
- 排除两个无须进入下一阶段的照搬项：MewCode 已有安全 truncated Tool 行为；partial assistant 是否写入 Conversation 是不同持久化选择，不构成功能缺口。
- 完成候选重新比较，正式选择 Stage 2A `AgentRun Control Plane`；ResourceScope 原设计保留并顺延。
- 创建 `docs/mewcode-agent-run-control-stage2a-design.md`，覆盖双队列、RunControl 状态机、Turn boundary、single-writer、hard stop、sealed race、TUI/Remote 协议和 Session flush。
- 将实施拆为 2A0–2A5：基线、RunControl、Loop/Run、Runtime facade、TUI/Remote、持久化/删除旧路径；每批先实现后补行为验证，不使用 TDD。
- 主路线升级到 v0.7：2A RunControl，2B TurnPreparer 设计门，ResourceScope/EventPipeline/Command 顺延；原资源详细设计增加顺延状态说明。
- 补齐 `RunInputDelivered`、typed `TurnComplete`、max-turn 延续条件和 `session_end` 真正停止点，消除设计中的事件/停止歧义。
- 校验新设计与主路线的 Markdown 围栏、相对文件存在性、行尾空白和 `git diff --check`；全部通过。
- 确认本轮只修改 docs 与 `.planning/`；`mewcode/` 和 tests 中的修改仍是此前未提交的 Stage 1 工作，本轮没有新增生产/测试改动。

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Source verification | 二手文章关键技术点有 Pi 官方源码/文档复核 | context snapshot、双队列、inner/outer loop、truncated gate 已复核 | passed |
| Design links/fences | 新详细设计与主路线链接存在、围栏平衡 | passed | passed |
| Markdown whitespace | 本轮设计/planning 无行尾空白 | no matches | passed |
| Git diff check | tracked diff 无 whitespace error | exit 0 | passed |

### Errors
| Error | Resolution |
|-------|------------|
| 首次 fence 校验把反引号放入 shell 双引号，zsh 报 `unmatched` | 未写入文件；改用单引号保护正则后重跑，校验通过 |

## Session: 2026-08-16 - Stage 2A implementation

### Current Status
- **Phase:** complete - Stage 2A implemented and verified

### Actions Taken
- 用户明确授权开始 Stage 2A 并持续到完成。
- 重新读取 `planning-with-files`、active goal、memory registry 和现有 Stage 2 planning；确认继续使用文件化计划且不使用 TDD。
- 将已完成的设计计划扩展为 Phase 9–15 实施与完成审计，保持 RunControl -> Loop/Run -> Runtime -> Adapter -> persistence -> full verification 顺序。

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Baseline target suite | existing Stage 0/1 target behavior green | `52 passed in 2.16s` | passed |
| Baseline diff check | no whitespace errors | exit 0 | passed |

### Actions Taken (continued)
- 审计当前分支 `codex/mewcode-extensionhost-stage-1@6578fa6` 与所有 tracked/untracked 变更；确认 Stage 2A 会与未提交 Stage 1 在四个文件上重叠，后续只做增量补丁。
- 运行开发前目标套件，AgentRun/ToolPipeline/Runtime/TUI/Remote/Agent 共 52 个测试通过。
- 复核当前 AgentRun/AgentLoop/EventSink/AgentRuntime 实现，固定 RunFinished 早于 settlement、EventSink backpressure、TurnComplete 不对称、session_end 提前和 max-turn 当前判断点等接入约束。
- 复核 TUI/Remote 输入、事件消费与 Session flush：确认 active 普通输入存在多个 drop/cancel 旁路，且自然 TurnComplete 需要 `will_continue` 防止空 UI row。
- Phase 9 基线冻结完成；开始实现不依赖 UI/Conversation/LLM 的 RunControl 核心。
- 新增 RunControl 深 Module 与稳定 runtime 导出，完成双 FIFO、typed directive、封口、max-turn 条件和跨类型顺序恢复。
- 在实现审查后新增 `tests/test_run_control.py`，11 个 RunControl Interface 测试通过。
- RunControl 加 Stage 0/1 目标回归共 `63 passed in 2.03s`；Ruff、compileall 和 diff-check 通过。
- Phase 10 完成，开始把控制面接入 AgentRun 与唯一 AgentLoop。

### Errors
| Error | Resolution |
|-------|------------|
| memory/AGENTS 组合搜索退出 1 | MEMORY 命中正常；仓库未发现 AGENTS.md，退出码来自第二个 `rg --files` 无匹配，不影响继续 |
| 2A2 首次静态检查发现 `agent_loop.py` 新类型注解缺少 `Literal` import（F821） | 补充 `from typing import Any, Literal`，随后重新运行静态检查 |
| 2A2 旧 Agent 测试仍断言只对 Tool Turn 发 `TurnComplete`，新增自然 Turn 后 2 个断言失败 | 这是已批准的生命周期合同变化；完成 2A2 行为审查后更新断言为每个完整模型 Turn 一次，并补 reason/will_continue 验证 |
| Adapter 结构搜索误把换行写进默认 rg 正则，rg 退出 2 | 前置静态检查均已通过；后续改用单行搜索或显式 multiline 模式 |
| 首次记录 Adapter 校验结果时 patch 上下文选到旧 session，随后多文件测试 patch 又含空 hunk | 两次均未写入目标文件；读取当前段并拆成按文件的明确补丁后完成 |
| TUI vertical test 断言共享 scripted client 只调用 2 次，实际为 4 次 | Agent 的 memory/consolidation 后台侧调用会复用 client；删除不属于 RunControl 合同的总调用次数断言，继续用 Conversation 与 Session 精确内容验证主 Run |
| Phase 14 扩大 Ruff 到整个 `mewcode/` 后发现 `tools/agent_tool.py:539` 的既有 F821 `AgentDef` | 目标测试 76 个均通过；该静态错误会阻塞最终门，先确认 TYPE_CHECKING/import 边界后做最小类型导入修正 |
| 修正 AgentDef 后全仓 Ruff 继续发现 `tests/test_memory.py:290` 缺少 `Any` import | 目标回归仍为 76 passed；检查测试文件 import 后补最小 typing 导入并继续全仓门 |
| Adapter 结构搜索把 `\n` 放进默认 rg 正则，rg 拒绝 literal newline 并退出 2 | 前置 Ruff/compileall/diff-check 已通过；改用分开的单行搜索或显式 `rg -U` 复查，不涉及代码错误 |
| 首次记录 Adapter 校验结果时 patch 上下文选到了旧 session 的 Errors 表 | 未修改文件；读取当前 implementation session 后把记录追加到正确位置 |

### Actions Taken (2A2 continued)

- 复核所有 `AgentLoop.run()` 与 `RunResult` 使用点；确认 legacy iterator、CLI、sub-agent 与 consolidation 可继续共享唯一 Loop，不需要兼容分叉。
- 复核 Turn 收尾辅助方法和 StreamingEventAdapter；确定下一步以跨 Turn 输入、hard stop 恢复、max-turn 与 hook 生命周期行为测试关闭 2A2，而不是恢复旧的 Tool-only `TurnComplete` 语义。
- 复核 Agent.start_run、RunControl 与 Hook 生命周期：确认每 Run 独立 Loop/Control，首轮只接收 steering，follow-up 只在自然边界投递，session_end 已覆盖所有实际停止路径。
- 在完整核心实现后补 AgentRun/AgentLoop 行为测试：覆盖首轮 steering、steering/follow-up 跨 Turn 优先级、delivery event、session_end exactly-once、cancel 恢复顺序、sealed 拒绝和 max-turn 未投递恢复；同步更新旧 TurnComplete 合同断言。
- AgentRun/AgentLoop/RunControl 目标测试 `43 passed`；Ruff、compileall、diff-check 全部通过。Phase 11 完成，进入 Runtime facade。
- 实现 AgentRuntime `steer_active_run()` / `follow_up_active_run()` 窄 facade；无 active run 返回 None，非 active Runtime 对 start/queue/cancel 统一拒绝，并在 Runtime composition 测试中补转发与 closed 边界。
- Runtime facade 累计目标测试 `57 passed`；Ruff、compileall、diff-check 全部通过。Phase 12 完成，进入 TUI/Remote Adapter 迁移。
- 定位 TUI 三类提交入口与 Remote WebSocket handler/event broadcast；确认将删除 TUI active cancel-restart 和 Remote active silent-return 两条旧路径。
- 确认两个入口可在保留 legacy event iterator 的同时经 Runtime facade 排队；识别 TUI 外层 task cancel 会截断 RunFinished，计划改为 AgentRun 协作式 cancel 并在 RunFinished 做最终 flush/restore。
- 完成 Adapter 事件块精读：锁定 TUI 条件创建 AI row 与 RunFinished final flush，Remote receipt/delivery/restored broadcast 三个修改点。
- 迁移 TUI 输入与事件路径：Alt+Enter 显式 follow-up，active 普通输入经 Runtime facade 排队并只渲染不写 Conversation/Session，TurnComplete 按 will_continue 建行，RunFinished final flush/restore，Escape 改为优先协作式取消 AgentRun。
- 迁移 Remote 协议：user_message 支持 delivery，active 输入返回 input_queued，Loop 投递返回 input_delivered，RunFinished 返回 input_restored/run_finished；删除 streaming silent-return 和 cancel 事件流提前 break。
- Adapter 初步回归与 core/runtime 累计 `35 passed`；Ruff、compileall、diff-check 通过，下一步补两个入口的运行中输入行为测试。
- 在实现完成后增加 Adapter 行为测试：TUI 键位/active queue/single-writer，Remote typed queued ack、delivered/restored ack 与 sealed race 新 Run 重试。
- TUI/Remote Adapter 行为测试 `10 passed`，Ruff、compileall、diff-check 通过；结构搜索确认 Remote 已无 `_cancel_event`，TUI 剩余 task cancel 仅为无 active-run fallback 与 shutdown。
- 精查剩余 cancel 行后修正上一判断：其中一处是 Ctrl-C active 分支而非 shutdown，已纳入 2A5 旧路径删除，不能留到完成审计。
- Ctrl-C 与 Escape 现统一优先调用 Runtime 协作式 cancel；只有没有 active AgentRun 的异常/fallback 状态才取消外层 UI task。
- 开始 2A5 持久化审计；发现首轮前部 context 注入可能移动 index-based history_cursor，并造成初始用户消息重复落盘，需在纵向 Session 测试前修正。
- 将 TUI Session flush 从可被前部注入移动的 list index 改为 Message identity anchor；Turn/Loop/RunFinished 共用同一 tail flush，compact boundary 后重置 anchor，避免首条和 queued 输入重复写入。
- 增加真实 TUI AgentRun 纵向测试，使用 gated 首轮在 streaming 中排入 steering，并核对 Conversation 与 Session 中首消息、queued 输入和两次回答均只出现一次。
- 增加真实 Remote AgentRun 纵向测试，以相同 gated 模型证明 Runtime facade queue、Core delivery、Conversation 顺序和 WebSocket ack 串联一致。
- 两个真实 Adapter 行为与纵向测试 `12 passed`；Ruff、compileall、diff-check 全部通过。Phase 13 完成，进入持久化/恢复/旧路径删除审计。
- 结构审计确认 active Conversation single-writer 与旧 drop/cancel 路径已删除；剩余修正是 Remote shutdown cancel race，以及补 terminate undelivered 证据。
- Adapter 对 Runtime closing/closed 的 queue/cancel 明确拒绝现已安全吸收，不会在 shutdown race 中启动新 Run 或打断 WebSocket/TUI handler。
- 补 terminate hard-stop 未投递恢复测试和 truncated retry 每 Turn 一次 TurnComplete 测试，关闭核心恢复矩阵的剩余证据。
- Phase 14 累计目标回归 `76 passed`；静态扩大检查暴露一处 AgentDef 类型名未在模块作用域导入的问题，进入最小修正。
- 将 AgentDef 移入已有 TYPE_CHECKING import 区并删除函数内无效导入，保持运行时行为不变，关闭全仓 F821 门。
- 为 test_memory 的 SessionRecord helper 补 `typing.Any`，只修复静态名称解析，不改变测试逻辑。
- Phase 14 目标矩阵 `76 passed`；全仓 Ruff、compileall、diff-check 全部通过。持久化、恢复与旧路径删除完成，进入最终全量与文档审计。
- 全量 pytest `693 passed, 1 skipped, 1 warning`；结构检查确认唯一 AgentLoop/ToolPipeline、RunControl 零入口依赖，开始同步两份仍标注“未实施”的设计文档。
- 详细设计与主路线升级为 implemented/v0.8，写入真实 2A0–2A5 结果、76 目标测试、693 全量测试、Message identity anchor 偏差与后续独立审批门。
- 过期状态搜索与 active-plan 指针检查通过；准备运行 planning-with-files 自带 completion/doctor gate。
- 复核技能 completion gate 实现；保持 Phase 15 in_progress 直到最后一轮验证真实完成，避免仅靠 checkbox 产生假完成。
- 最终 audit 启用 `check` 的 Plan Execution 模式；下一步按其 dirty-worktree 要求做隔离的 Stage 1+2A 验证，不执行 commit/push 或普通 PR specialist review。
- 记录 review preflight：branch/HEAD 未漂移，工作树内容与 Stage 1+2A 及用户学习材料清单一致；项目没有额外 test runner，准备临时 detached worktree 验证。
- 临时 detached worktree 隔离重放验证通过：目标 `76 passed`，全量 `687 passed, 1 skipped, 1 warning`，Ruff/compileall/diff-check 通过；trap 删除临时 worktree。
- `check` Plan Execution 审计结论为 on target、无未解决 hard stop、无 public action；两份设计文档同步隔离与当前树证据，Phase 15 完成。

### Final Verification

| Gate | Result |
|------|--------|
| Stage 2A target matrix | `76 passed` |
| Current worktree full pytest | `693 passed, 1 skipped, 1 warning` |
| Isolated Stage 1+2A full pytest | `687 passed, 1 skipped, 1 warning` |
| Ruff F/E fatal checks | passed |
| compileall | passed |
| git diff whitespace | passed |
| Structure and dependency searches | passed |
| Planning links/fences/active-plan | passed |

Final planning-with-files gate: `ALL PHASES COMPLETE (15/15)`。临时 detached worktree 已清理，当前仅保留原工作树；HEAD 仍为 `6578fa6c5394dc2ef0ce6c260241f9ba623f279c`，未 commit、未 push。

## Session: 2026-08-16 - Stage 2B TurnPreparer implementation

### Current Status
- **Phase:** complete - Stage 2B implemented and verified

### Actions Taken
- 用户授权开始开发，继续采用“生产实现完成后补行为测试”的非 TDD 流程。
- 对照当前 Pi Agent Loop 与 MewCode 实现，确认单层 Loop + RunControl、ToolPipeline 和 drain-all 语义均保持不变。
- 新增 `TurnPreparer` 与不可变 `PreparedModelCall`，把每轮模型调用前的 Context preparation 从 `_run_loop()` 集中到一个 `prepare()` Interface。
- 把 Hook 调度实现收回 `Agent._run_hook()`，供 AgentLoop 与 TurnPreparer 共用；删除 AgentLoop 的浅转发方法。
- 生产实现完成后新增 TurnPreparer Interface 测试和真实慢 Tool batch 输入投递测试。
- 更新 Runtime 主路线与 active planning，Stage 2B 标为已实施；下一候选是 2C ResourceScope + TaskSupervisor 复核。

### Verification

| Gate | Result |
|------|--------|
| Stage 2B related target suite | `42 passed` |
| Current worktree full pytest | `696 passed, 1 skipped, 1 warning` |
| compileall | passed |
| git diff whitespace | passed |
| Ruff | unavailable in current restricted environment; not claimed |

### Errors

| Error | Resolution |
|-------|------------|
| `uv run` 读取默认 uv cache 时被当前 filesystem policy 拒绝 | 改用仓库现有 `.venv/bin/python`，目标与全量测试均通过 |
| `.venv/bin/ruff`、PATH Ruff 和 Python Ruff module 均不存在 | 未安装依赖或绕过权限；如实记录本阶段未运行 Ruff |
