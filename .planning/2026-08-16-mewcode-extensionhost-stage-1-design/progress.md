# Progress Log

## Session: 2026-08-16

### Current Status
- **Phase:** Complete - Stage 1 design and planning
- **Scope:** 只修改设计和规划文档，不修改 `mewcode/` 生产代码
- **Started:** 2026-08-16

### Actions Taken
- 完整读取 `planning-with-files` 与 `codebase-design` 技能说明，以及模块深化检查表。
- 恢复已完成的阶段 0 active plan，读取其 `task_plan.md`、`findings.md` 和 `progress.md`。
- 运行 session catch-up；没有发现未同步的规划上下文。
- 初始化并激活独立的阶段 1 计划目录。
- 固定阶段 1 的范围、非目标、六个设计阶段和生产代码审批门。
- 完成项目记忆快速查询；只继承“教学案例与生产设计分离”的范围约束，具体架构以当前仓库为准。
- 复核 Runtime 主设计的总体架构与深模块章节，确认阶段 1 必须把终局 ExtensionHost 收窄成内置 Tool 纵向切片。
- 用 Pi 官方 Extensions/SDK 文档复核异步工厂、Tool 来源信息以及 ResourceLoader 与 Session 激活分离的语义。
- 对照阶段 0 Interface 测试和主设计总测试表，确定 Stage 1 只新增 Host 所有权与 profile 契约测试，不让 Loop/Pipeline 测试穿透新模块。
- 完成当前问题矩阵：重复装配、静默覆盖、无撤销、部分启动、Agent 依赖环、profile 漂移、父子所有权、生命周期和 MCP 来源。
- 创建 `docs/mewcode-extension-host-stage1-design.md`，完成 Tool-only 范围、深模块 Interface、状态机、profile、回滚、AgentRuntime 集成、borrowed ToolView、MCP 适配、1A-1F 迁移和验收设计。
- 按 Tool 类源码复核 profile 名称，将 TUI 的交互提问 Tool 校正为真实名称 `AskUserQuestion`。
- 把主设计升级到 Design v0.4，加入阶段 1 详细设计入口，并修正 TUI 文件、四个 profile、borrowed ToolView、MCP Handle 和 1A-1F 路线。
- 同步主设计的阶段 0 已完成决策，并把阶段 1 下一步改为详细设计评审后从 1A 行为刻画开始。
- 最终 Git 审计发现外部状态已把阶段 0 提交为 `6578fa6` 并切到 `codex/mewcode-extensionhost-stage-1`；本轮未执行分支或提交操作，当前未提交范围不含 `mewcode/` 生产文件。

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Active plan | 指向独立的阶段 1 目录 | `2026-08-16-mewcode-extensionhost-stage-1-design` | passed |
| Session catch-up | 报告未同步上下文或安静结束 | 无未同步输出 | passed |
| 生产代码边界 | 本轮开始时不新增阶段 1 生产修改 | 尚未进行生产代码修改 | passed |
| 设计文档相对链接 | 所有 `./` Markdown 目标存在 | 5 个唯一目标全部存在 | passed |
| Markdown 围栏 | 两份设计文档围栏成对 | 主设计 8、阶段 1 设计 24，均为偶数 | passed |
| 行尾空白 | 设计与阶段 1 planning 文件无行尾空白 | 无匹配 | passed |
| 旧 Stage 1 假设 | 交付文档无“9 文件/三入口一致/AskUser 错名/待确认”残留 | 仅 planning findings 保留一条历史问题说明 | passed |
| Git patch 格式 | 当前工作区 diff 无空白或 patch 错误 | `git diff --check` 通过 | passed |
| 生产代码边界（最终） | Stage 1 设计不产生未提交 `mewcode/` 修改 | `git status --short` 只显示设计/规划和既有学习材料 | passed |
| 生产目录精确审计 | `mewcode/` 既无 tracked diff，也无 untracked 文件 | 两项检查均为空 | passed |
| 产品测试 | 设计阶段不假装验证未实现行为 | 未运行，符合“先不修改代码”范围 | not_run |
| Planning completeness | 所有阶段完成 | `ALL PHASES COMPLETE (6/6)` | passed |

### Errors
| Error | Resolution |
|-------|------------|
| 技能首次组合读取输出被上下文截断 | 使用行数和分段读取完整恢复两个 `SKILL.md` |
| 并行源码读取触发 `Too many open files (os error 24)` | 记录后改为单个顺序命令，后续不再并行启动本地进程 |
| 合并的顺序 `rg + sed` 仍触发文件描述符上限 | 作为第二次同类失败记录，下一步拆成单一小命令，不重复合并读取 |
| 非关键 pyproject 读取第三次触发同类错误 | 结束该探索分支；信息不是设计决策前提，后续只运行最小校验命令 |

## Session: 2026-08-16 - Stage 1 实施

### Current Status
- **Phase:** Complete - Stage 1A–1F implemented and verified
- **Scope:** 按 `docs/mewcode-extension-host-stage1-design.md` 实施 Stage 1A-1F，直到全量验证成功

### Actions Taken
- 用户明确授权“开始开发，直到完成和验证成功”。
- 完整读取 `planning-with-files` 和 `tdd` 技能，以及 TDD 的测试与 mocking 指南。
- 恢复 active plan、findings、progress，并运行 session catch-up；没有未同步上下文。
- 将已完成的设计计划扩展为 Phase 7-13 实施与完成审计。
- 确认 TDD seams 已由详细设计和用户开发授权共同确认：ToolRegistry、ExtensionHost/Session、AgentRuntime、ToolView/Profile。
- 检查仓库指令文件，没有 `AGENTS.md` 或 `CONTEXT.md`；完成项目记忆快速查询，继续保持教学 Demo 与生产 Stage 1 分离。
- 复核 `pyproject.toml`、ToolRegistry 和测试引用；确认 Python 3.11+、无额外插件依赖，并确定新增 `tests/test_tool_registry.py` 的公开 Interface seam。
- TDD cycle 1 red：新增 ToolRegistry 重复注册契约测试，要求拒绝重复名称且保留 original Tool。
- TDD cycle 1 green：实现最小 `ToolConflictError` 和重复名称快速失败，目标测试通过。
- TDD cycle 2 red：新增四个 ToolProfile 的确切名称与顺序契约测试。
- TDD cycle 2 green：新增最小 `mewcode.extensions` package、ToolProfile 和有序名称 manifest，四个 profile 契约通过。
- TDD cycle 3 red：新增 RegistrationHandle 精确幂等注销与 disabled/discovered 清理契约。
- TDD cycle 3 green：实现 registration identity Handle；精确注销、重复 close 和状态清理通过。
- TDD cycle 4 red：新增 ContributionOwner、贡献列表与冲突双方来源诊断契约。
- TDD cycle 4 green：ToolRegistry 内部改为 ToolContribution，保留 Tool 查询投影，并提供 owner/source/sequence 冲突诊断。
- TDD cycle 5 red：新增 ExtensionHost 成功激活、Session 诊断、反向所有权清理和幂等关闭契约。
- TDD cycle 5 green：实现 Catalog、Host、extension-scoped API、Session 和 async 生命周期，成功激活/关闭测试通过。
- Host rollback coverage：新增单扩展第二次注册冲突时回滚第一次注册的契约；因 cycle 5 green 已包含 critical rollback，该测试直接通过。
- Host Interface coverage：补充 prior-extension rollback、noncritical isolation、active/closed API sealing 和重复 extension ID 契约。
- TDD cycle 6 red：新增 installer 取消必须回滚且原样传播 CancelledError 的契约。
- TDD cycle 6 green：Host 对 CancelledError/SystemExit/KeyboardInterrupt 类 BaseException 先回滚后原样传播，不按 noncritical 隔离。
- TDD cycle 7 red：新增 AgentRuntime 对 Agent、Registry、ExtensionSession、Run 取消/等待和幂等关闭的公开 Interface 契约。
- TDD cycle 7 green：实现 AgentRuntimeRequest、空 Registry 构造约束、Host 激活、Run 委托、取消/等待和 async 幂等关闭。
- TDD cycle 8 red：内置 prompt manifest 测试因 `BuiltinRuntimeBindings` 尚未导出而 collection 失败。
- TDD cycle 8 green：实现固定字段 bindings、共享 FileStateCache、有序 Tool factory 和内置 ExtensionHost；Runtime/profile/Schema/owner/close 契约 `9 passed`。
- prompt tracer bullet：`_run_prompt()` 已删除 `create_default_registry()` 与逐个内置注册，改为 `PROMPT_LEAD` AgentRuntime + typed bindings；运行主体置于 Runtime async context，包含无 team 的早退路径。
- prompt 入口集成测试使用最小真实 AgentRun/PromptClient 验证 `prompt-ok` 输出、Runtime closed 和 contribution 清零；删除了后来新增但更弱的 mock-only 重复测试。
- TDD cycle 8 red：新增 PROMPT_LEAD typed bindings、真实内置 Tool factory、Schema/顺序、provenance 与关闭清理契约。
- TDD cycle 8 green：实现 BuiltinRuntimeBindings、四 profile 有序 factory manifest、依赖校验与 builtin Host；四个 profile 均以真实 Tool/Schema 通过。
- TDD cycle 9 red：真实 prompt end_turn 行为保持输出，但 Runtime 记录仍为 active，证明入口尚未统一关闭。
- TDD cycle 9 green：prompt 使用 PROMPT_LEAD AgentRuntime 与 `async with` 包住事件循环和无 team 早退；真实 AgentRun 后 Runtime closed 且 Registry 为空。
- Stage 1D targeted/full：Runtime/Host/Registry/Agent 目标集 47 passed；删除重复 mock-only 测试后的权威全量为 654 passed、1 skipped，只有既有 timeout mark warning。
- TDD cycle 10 red：新增 TUI provider 初始化必须 awaitable 的 Adapter 契约，旧同步 `_select_provider` 失败。
- TDD cycle 10 green：`on_mount`、provider 选择事件与 `_select_provider` 全部改为 async/await；TUI focus、mascot、UI state 目标集 `18 passed`。
- TDD cycle 11 red：真实 Textual mount 后没有 `app.runtime`，证明 awaitable 初始化仍在使用默认 Registry 与手工 Tool 装配。
- TDD cycle 11 green：TUI_LEAD Runtime 接管真实 Tool 装配，typed bindings 保留 Skill/Worktree/Team/sandbox/file-history；新增 MCP 后 Runtime 关闭位置。
- TDD cycle 12 red：Remote `_init_agent()` 返回 None，不可等待且没有 Runtime owner。
- TDD cycle 12 green：Remote 初始化改为 REMOTE_LEAD Runtime，server `run()` finally 按 MCP → Runtime → Session 顺序关闭。
- Stage 1E targeted/full：TUI/Remote/Runtime/UI 目标集 36 passed；全量 658 passed、1 skipped，只有既有 timeout mark warning。
- TDD cycle 13 red：新增 borrowed ToolView 可见性、来源、只读与关闭不影响父 Registry 的契约；collection 因 Interface 不存在失败。
- TDD cycle 13 green：实现只读 ToolView snapshot、borrowed provenance、local additions 与幂等 close；sub-agent/fork/teammate/coordinator 过滤路径统一返回 view。
- TDD cycle 14 red：external teammate 测试改为要求 `_open_teammate_runtime()`；旧 helper 不存在 owned Runtime，collection ImportError。
- TDD cycle 14 green：TEAMMATE_WORKER 使用独立 Runtime/Session，worker finally 按 MCP → Runtime 关闭；协作 Tool 与角色限制回归通过。
- TDD cycle 15 red：MCP 同名冲突仍向上抛出，已注册的同 server Tool 未回滚，且没有来源/Handle owner。
- TDD cycle 15 green：MCP 按 server 保存 Handle 与 runtime provenance；单 server 冲突回滚本批并继续后续 server，shutdown 先反向注销再关 client。
- Stage 1F targeted/full：ToolView、teammate、MCP、四入口与角色过滤目标集 166 passed；全量 662 passed、1 skipped，只有既有 timeout mark warning。
- 结构搜索确认 TUI/prompt/Remote/external teammate 不再调用 `create_default_registry()` 或逐个注册内置 Tool；剩余 register 是 AgentNameRegistry 与 MCP 动态 contribution。
- TDD cycle 16 red/green：第二次 TUI provider 初始化先因重复 Command 暴露旧 Runtime 未清理；现改为先验证新 client，再关闭 MCP/旧 Runtime 和旧后台任务，重建 provider-scoped managers，确保只保留一个 active Runtime。
- TDD cycle 17 red/green：Runtime 关闭时 coordinator borrowed ToolView 原先仍 active；现先关闭 view 并把 Agent 恢复到主 Registry，再关闭 ExtensionSession。
- 完成审计目标矩阵（Registry/Host/Runtime/TUI/Remote/MCP/teammate/subagent/Stage 0）最终 `271 passed`。
- TUI Runtime composition：重排 Skill/Worktree/Team/Sandbox 依赖，在注册前创建 typed bindings；TUI_LEAD 由 AgentRuntime 原子激活，App 保留 `agent/registry` 兼容引用，不再逐个注册内置 Tool。
- TUI shutdown 已提供幂等 `_shutdown_runtime()`，退出顺序明确保持 MCP shutdown 在 Runtime close 之前。
- 新增真实 Textual `run_test()` 覆盖单 provider 初始化：TUI profile/owner/Agent/Registry 同一性及关闭清零均通过，`2 passed`。
- TDD cycle 11 red：Remote shutdown 顺序正确但第二次调用重复关闭 Session，幂等契约失败。
- TDD cycle 11 green：Remote 关闭后清空 Session 引用；真实 REMOTE_LEAD 初始化与 MCP→Runtime→Session 幂等关闭测试通过，TUI/Remote 目标集 `25 passed`。
- TDD cycle 12 red：external teammate 契约已改为要求 `_open_teammate_runtime()` 与关闭后 contribution 清零，collection 因该 Runtime Adapter 尚不存在失败。
- TDD cycle 12 green：external teammate 以 TEAMMATE_WORKER Runtime 构造，连接 SkillLoader，并在 worker finally 中先关 MCP、后关 Runtime；关闭后 owned contribution 清零。
- ToolView adapters：resolve/background、fork replacement、coordinator 与 in-process teammate 已使用 borrowed view；child-local coordination Tool 显式覆盖同名父投影，129 项 teammate/subagent/team/registry 回归通过。
- TDD cycle 13 red：MCP Handle/provenance 测试显示 owner 已有 server 来源但缺少目标 Runtime 的 id/generation。
- TDD cycle 13 green：MCPManager 从 Registry 唯一 owned Runtime 继承 identity，按 server 保存/回滚 Handle，shutdown 反向注销后关闭 client；`22 passed`。
- Stage 1F full regression：新增 App/Remote/teammate/ToolView/MCP 契约后全量 `663 passed, 1 skipped, 1 warning`。
- Final gate 首次 `git diff --check` 发现 `__main__.py` 动态缩进产生的空白行尾；这是纯格式问题，使用机械去行尾空白后重跑 gate。
- 行尾修复确认根因是旧 CRLF 与新 LF 混合产生独立 `\r` 空白行；机械统一本轮触及的 `__main__.py`/`tool_filter.py` 为 LF 后 `git diff --check` 通过。
- 项目 `.venv`、系统 PATH 与 pyproject 均未提供 Ruff；最终 gate 将用临时 `uvx ruff` 执行，不把工具加入项目依赖。
- `uvx ruff check mewcode tests` 成功运行但报告 406 个仓库级既有 lint 问题（跨大量未触及模块/测试），不能把全仓清理扩入 Stage 1；改用全仓致命规则 gate，并对本轮新增模块运行严格 E/F/I 检查，单独修复本轮引入项。
- 致命规则首次定位到 TUI 迁移时误删但仍用于类型/运行时判断的 LoadSkill、InstallSkillTool、AskUserTool 导入；已恢复，并用 TYPE_CHECKING 补齐 App 内三个 forward UI event 类型。
- scoped Ruff 命令最初包含已在去重中移除的两份临时 Runtime 测试文件，产生 E902；更新为当前 `rg --files` 权威清单后重跑。
- 当前 Stage 1 文件的 Ruff 致命规则（E9/F63/F7/F82）全部通过；新增 extensions/AgentRuntime/Interface 测试再通过严格 E/F/I。Ruff 仅对这些新增文件执行安全 import/format 修复，未扩散清理 406 个既有仓库问题。
- `compileall -q mewcode tests` 与 `git diff --check` 已通过；完成审计开始补双 Runtime 隔离、prompt 异常关闭和 Host close-failure 的直接行为证据。
- 新增并通过双 Runtime registry/tool/state 隔离、Runtime A 关闭不影响 B、prompt Agent run 异常仍关闭、Host 某 Handle close 抛错仍清理其他 contribution 的行为测试；目标集 `20 passed`。
- TUI 增加 provider 初始化锁：并发选择串行化，第二次初始化先关闭 MCP/旧 Runtime 和会话级任务，再创建新 Runtime；真实 Textual 并发测试证明第一个 closed、最终仅第二个 active，TUI 目标集 `16 passed`。
- external teammate 取消路径通过完全隔离的 worker Adapter 测试：handle 收到 cancel，finally 关闭 Runtime；`tests/test_teammate_registry.py` 3 passed。
- 最终权威全量回归：`669 passed, 1 skipped, 1 warning`；warning 仍是既有 `tests/test_consolidation.py:140` 未注册 timeout mark。
- 最终 compileall、`git diff --check`、设计文档相对链接和重复装配结构搜索通过；Stage 1 状态同步到两份设计与 planning。
- 工作区审计确认用户既有 Mini Plugin/Cordis 学习文档、examples 和 `tests/test_mini_pi_agent.py` 未被本阶段修改。
- TDD cycle 14 red/green：Runtime close 前注入 legacy contribution 时，初版 diagnostics 无泄漏记录；现已保留残留 contribution 并追加 name/owner/source 的 `leaked` 诊断，Runtime composition `14 passed`。
- 审计发现双 Runtime 隔离与 Runtime 关闭 borrowed ToolView 已有更完整测试，删除后来追加的重复隔离用例，保留异常 prompt 与 leak diagnostics 新证据。
- 最终补强测试和去重后再次验证：目标矩阵 `271 passed`；全量 `669 passed, 1 skipped, 1 pre-existing warning`。
- Patch hygiene：`__main__.py`/`tool_filter.py` 原文件为 CRLF；曾全量转 LF 导致整文件 diff。按 baseline equal blocks 恢复原行尾、仅让变更块使用 LF，并去掉 CR-only 空白行后，`git diff --check` 再次通过且 diff 明显收窄。
- TDD cycle 15 red/green：真实 profile 工厂允许缺失 SkillLoader 而生成半初始化 LoadSkill/InstallSkill；现改为激活期必填校验，缺依赖触发 ExtensionStartupError 并原子回滚，Runtime composition `14 passed`。

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Git baseline | Stage 0 提交作为 Stage 1 起点 | `codex/mewcode-extensionhost-stage-1@6578fa6` | passed |
| Clean production baseline | 实施前无未提交 `mewcode/` 修改 | status 仅含设计/planning 与既有学习材料 | passed |
| Full pytest baseline | 现有测试在 Stage 1 修改前通过 | `635 passed, 1 skipped, 1 warning` | passed |
| TDD cycle 1 red | 重复 Tool 注册测试只因缺少新冲突契约失败 | collection 因 `ToolConflictError` 不存在失败 | expected_fail |
| TDD cycle 1 green | 重复 Tool 注册被拒绝且 original 保留 | `1 passed` | passed |
| TDD cycle 2 red | profile 契约只因扩展包尚不存在失败 | collection 因 `mewcode.extensions` 不存在失败 | expected_fail |
| TDD cycle 2 green | 四个 profile 返回设计中固定的名称和顺序 | `4 passed` | passed |
| Stage 1A compatibility | ToolSearch、teammate、sub-agent、AgentRun 现有行为不回归 | `84 passed` | passed |
| TDD cycle 3 red | Handle 测试只因 register 仍返回 None 失败 | `1 failed, 1 passed`，AttributeError on `None.close()` | expected_fail |
| TDD cycle 3 green | Handle 精确注销、重复 close 和状态清理 | `2 passed` | passed |
| TDD cycle 4 red | 来源诊断测试只因 ContributionOwner 尚不存在失败 | collection ImportError | expected_fail |
| TDD cycle 4 green | Registry 贡献、冲突来源和 ToolSearch 兼容 | `14 passed` | passed |
| Stage 1B full regression | Contribution 内部改造不破坏现有 Tool/Agent 行为 | `642 passed, 1 skipped, 1 warning` | passed |
| TDD cycle 5 red | Host 生命周期测试只因 Host/Catalog Interface 不存在失败 | collection ImportError | expected_fail |
| TDD cycle 5 green | Host 成功激活、诊断、反向清理和幂等关闭 | `1 passed` | passed |
| Host partial rollback coverage | 第二次注册冲突后只保留启动前 contribution | `2 passed`；测试直接通过，已记录 TDD 偏差 | passed |
| TDD cycle 6 red | 取消激活未原样传播 | test did not raise CancelledError | expected_fail |
| TDD cycle 6 green | 取消激活回滚并原样传播，Host 契约全通过 | `6 passed` | passed |
| Stage 1C full regression | Host 事务核心不破坏现有运行时 | `648 passed, 1 skipped, 1 warning` | passed |
| TDD cycle 7 red | Runtime 生命周期测试只因 AgentRuntime Interface 不存在失败 | collection ImportError | expected_fail |
| TDD cycle 7 green | Runtime 只在 Session active 后暴露，关闭清空 owned contribution | `5 passed` | passed |
| TDD cycle 8 red | typed bindings 与内置 Host 尚不存在 | collection ImportError | expected_fail |
| TDD cycle 8 green | prompt manifest 名称、Schema、owner 与关闭清理一致 | `9 passed` | passed |
| Prompt tracer targeted | Runtime/Host/Registry 与入口编译及目标契约 | `19 passed`，py_compile 通过 | passed |
| TDD cycle 8 red | 内置 manifest 测试只因 BuiltinRuntimeBindings 尚不存在失败 | collection ImportError | expected_fail |
| TDD cycle 8 green | 四 profile 的真实 Tool 名称、Schema、来源和关闭清理一致 | `9 passed` | passed |
| TDD cycle 9 red | prompt 完成后必须关闭 Runtime | `1 failed`，state 为 active | expected_fail |
| TDD cycle 9 green | prompt 输出不变且 Runtime/owned Registry 已关闭 | `1 passed` | passed |
| Stage 1D targeted regression | Runtime composition、Host、Registry、AgentRun | `47 passed` | passed |
| Stage 1D full regression | prompt tracer 不破坏既有产品行为 | `654 passed, 1 skipped, 1 warning` | passed |
| TDD cycle 11 red | TUI mount 必须暴露 owned Runtime | `1 failed`，AttributeError on `app.runtime` | expected_fail |
| TDD cycle 11 green | TUI profile、Registry ownership 与关闭归零 | `1 passed` | passed |
| TUI Runtime adapter regression | input focus、mascot、clear 行为不回归 | `16 passed` | passed |
| TDD cycle 12 red | Remote 初始化必须可等待并拥有 Runtime | `1 failed`，`_init_agent()` returned None | expected_fail |
| TDD cycle 12 green | Remote profile、Registry ownership 与 shutdown 归零 | `1 passed` | passed |
| Stage 1E targeted regression | TUI、Remote、UI 与 Runtime Adapter | `36 passed` | passed |
| Stage 1E full regression | 入口迁移不破坏既有产品行为 | `658 passed, 1 skipped, 1 warning` | passed |
| TDD cycle 13 red | ToolView 必须显式建模 borrowed ownership | collection ImportError | expected_fail |
| TDD cycle 13 green | view 关闭只清理本地投影，父贡献保持不变 | `4 passed`；过滤路径回归 `129 passed` | passed |
| TDD cycle 14 red | external teammate 必须拥有独立 Runtime | collection ImportError | expected_fail |
| TDD cycle 14 green | teammate profile/close 与 in-process 过滤保持正确 | `123 passed` | passed |
| TDD cycle 15 red | MCP 冲突必须局部回滚而非中断整个注册 | `1 failed`，ToolConflictError escaped | expected_fail |
| TDD cycle 15 green | provenance、局部回滚、后续 server 与幂等 shutdown | `23 passed` | passed |
| Stage 1F targeted regression | ToolView、teammate、MCP、入口与过滤 | `166 passed` | passed |
| Stage 1F full regression | 所有权迁移不破坏既有产品行为 | `662 passed, 1 skipped, 1 warning` | passed |
| Duplicate assembly search | 四生产入口没有旧默认 Registry/内置 Tool 手工注册 | 仅 AgentNameRegistry 与 MCP 动态注册保留 | passed |
| TDD cycle 16 | TUI provider 切换只保留一个 active Runtime | red: duplicate worktree Command；green: `1 passed` | passed |
| TDD cycle 17 | Runtime close 同时清理 borrowed coordinator view | red: view state active；green: `1 passed` | passed |
| Final Stage 1 target matrix | Interface、四入口、MCP、多 Agent 与阶段 0 回归 | `271 passed` | passed |
| Final full pytest | 全仓行为回归 | `669 passed, 1 skipped, 1 warning` | passed |
| Final current-worktree audit | scoped Ruff、compileall、diff-check、结构搜索、文档链接与围栏 | 全部 exit 0 | passed |
| Compile and patch gates | compileall 与 diff whitespace | 两项 exit 0 | passed |
| Design links and structure | 相对链接有效，四入口无重复内置装配 | 无缺失链接；仅 MCP 动态注册保留 | passed |

### Errors
| Error | Resolution |
|-------|------------|
| 两次 planning patch 使用了错误文件锚点，随后一次写入旧 session 表格 | 使用 Stage 1 实施 session 的唯一标题上下文移动记录，未触碰生产文件 |
| `uv run pytest` 因沙箱不能读取 `~/.cache/uv/sdists-v9/.git` | 改用仓库 `.venv/bin/pytest`，不重复失败命令、不请求额外权限 |
| 首次创建 profile 测试误用了空 Update hunk | 改为完整 Add File patch，空 hunk 未产生文件变更 |
| Host 首个 green 提前包含 critical partial rollback | 保留正确实现并补覆盖；后续新能力严格先写可观察失败测试 |
| TUI 装配体动态替换沿用旧行号，误删除后继两个 async 方法 | 真实 TUI Runtime 测试立刻报 `_resolve_context_window` AttributeError；恢复方法并重跑 `2 passed` |
| 最终重复 Ruff 下载尝试在全新临时目录被网络沙箱拒绝 | 使用本轮更早已成功完成的临时 Ruff gate 结果；随后 compileall、全量 pytest 与 diff-check 再次通过，未把 Ruff 加入项目依赖 |
| 首版文档链接校验脚本使用了 zsh 不接受的参数模式 | 改用 `sed` 提取相对路径后重跑；两份设计文档的相对链接与代码围栏校验通过 |
