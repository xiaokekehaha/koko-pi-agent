# Findings & Decisions

## Requirements
- 使用 `planning-with-files` 持久化阶段 1 的计划、发现和进度。
- 在已完成阶段 0 的基础上设计 ExtensionHost；不重新设计 AgentLoop 或 ToolPipeline。
- 从一个计划修改的模块给出具体步骤和修改理由，先让用户理解，不修改生产代码。
- 以当前 MewCode 为唯一产品主体，不实现 Mini Pi 平行框架。
- 用户已授权按阶段 1 详细设计开始开发，持续到完成并验证成功。
- TDD seams 已在详细设计中预先确认：ToolRegistry、ExtensionHost/ExtensionSession、AgentRuntime、ToolView/ToolProfile；不得通过私有状态断言实现细节。

## Research Findings
- Stage 1 实施起点是 `codex/mewcode-extensionhost-stage-1@6578fa6`；当前未提交内容只有阶段 1 设计/planning 与用户既有学习材料，没有 `mewcode/` 生产修改。
- 仓库没有 `AGENTS.md` 或 `CONTEXT.md`；实施以阶段 1 详细设计、现有测试命名和源码约定为准。
- 项目记忆仍只约束 Mini Plugin Agent 教学案例不能自动当作生产实现授权；当前用户对 Stage 1 的明确开发授权已经满足新的实施门，具体行为以当前仓库为准。
- 项目要求 Python >=3.11，dev 依赖只有 pytest 与 pytest-asyncio；Stage 1 可直接使用 AsyncExitStack、dataclass、Enum 和 async tests，不增加运行时依赖。
- 当前没有独立 `tests/test_tool_registry.py`；ToolRegistry 只被 Agent/Tool/Permission/Skill 等测试间接覆盖，Stage 1B 需要新增公开 Interface 契约测试。
- `create_default_registry()` 仍是六个基础 Tool 的唯一共享工厂，但所有完整入口会在其后手工追加不同 Tool；它可在迁移期保留给轻量测试，生产入口最终不得依赖它完成完整装配。
- 当前权威测试基线由仓库 `.venv/bin/pytest` 运行：收集 636 项，`635 passed, 1 skipped`；唯一 warning 是既有 `tests/test_consolidation.py:140` 未注册的 timeout mark。
- 项目记忆只确认 `docs/plugin-agent-learning-design.md` 是独立教学案例，不是生产 MewCode 的实现基线；本阶段必须以当前仓库和 Runtime 设计为准。
- 旧教学范围曾明确排除动态导入、并发、MCP、多 Agent、会话隔离与生产代码变更，因此不能把它直接升级成阶段 1 的 ExtensionHost 设计。
- 本轮开始时分支是 `codex/pi-inspired-runtime-design`，阶段 0 生产修改仍在工作区；最终审计时外部状态已把阶段 0 提交为 `6578fa6 feat: unify agent runtime and tool pipeline`，并切到 `codex/mewcode-extensionhost-stage-1`。本轮没有执行分支、提交或重置命令。
- 主设计已把进程级 `ExtensionHost` 与每个 Agent Runtime 独立的 `ExtensionSession` 分开，并明确阶段 0 的 `ToolPipeline` 只依赖稳定的 ToolRegistry 接缝。
- 当前主设计描述的是终局能力：Tool、Command、事件、资源、后台任务、发现与重载；阶段 1 只应走通“内置 Tool”纵向切片，不能把终局全部一次实现。
- 阶段 1 的关键设计问题不是再画总体架构，而是确定最小 Interface：谁创建 Catalog、谁打开 Session、ToolRegistry 由谁拥有、安装失败如何原子回滚、关闭后 Registry 如何验证为空。
- 主设计要求启动失败时先反向清理已注册能力、关键内置扩展失败则 Runtime 创建失败；关闭必须幂等并在拒绝新工作后反向撤销注册。
- Tool Contribution 至少需要名称、实现、extension_id、来源、注册序号和 runtime generation；同名 Tool 默认快速失败，RegistrationHandle 只能撤销自己拥有且仍属同一 generation 的记录。
- 阶段 1 的 `AsyncExitStack` 只需作为 ExtensionSession 的内部注册回滚机制；通用资源托管和 TaskSupervisor 仍属于阶段 2A，不应提前暴露到 ExtensionAPI。
- 既有阶段 1 文件表是方向性估算，必须以当前真实组合根和 Agent 创建路径重新校验，不能机械按“9 个文件”实施。
- 当前 `ToolRegistry.register()` 是静默覆盖且返回 `None`；Registry 还同时保存 enabled/disabled 与 deferred-discovered 状态，阶段 1 必须保持这些现有读取行为。
- 内置 Tool 并非只在 `mewcode/__main__.py` 和 `remote.py` 装配：`mewcode/app.py` 也有完整 TUI 装配，`agents/tool_filter.py` 会创建过滤/克隆 Registry，MCP 还会在连接后动态注册 Tool。
- 主设计原文件表漏掉 `mewcode/app.py`，而 `__main__.py` 同时存在 prompt 模式与 teammate 模式两组装配；“三种入口清单一致”必须按能力 profile 比较，不能要求不同角色拥有完全相同 Tool。
- MCP Tool 属于运行期外部连接贡献，虽然仍要兼容 ToolRegistry 的新冲突规则，但不宜在 Stage 1 被包装成内置扩展；否则会把发现、连接资源和注销问题提前带入 Tool-only 切片。
- `MewCodeApp._select_provider()` 既创建 Registry/Agent，又在 Agent 创建前后分批注册依赖不同的 Tool；许多 Tool 需要 `Agent`、TeamManager、WorktreeManager、SkillLoader 或回调，不能由一个无上下文的静态 `create_default_registry()` 完成。
- TUI 关闭流程目前手工并发执行 memory、Hook、MCP 清理，3 秒后取消并吞掉异常；阶段 1 不应顺手接管这些资源，但必须为 ExtensionSession 增加明确关闭位置，并保证重复关闭安全。
- TUI 在 Registry 建成后可能用 `apply_coordinator_filter()` 替换 `agent.registry`，而 App 仍保留原 `self.registry`；这是 Stage 1 的重要所有权风险：过滤后的派生 Registry 不应被误认为 ExtensionSession 的主 Registry。
- prompt 入口把“基础 Tool → Agent → 依赖 Agent 的团队 Tool”分两段装配，函数退出时没有统一 Runtime/Registry 关闭；teammate 入口的 MCPManager 只保存在局部变量中，注册后没有显式 shutdown 所有者。
- Tool 工厂存在依赖环：`AgentTool`、`TeamCreateTool`、`TeamDeleteTool` 构造时需要已经创建的 parent Agent，而 Agent 构造时又需要 Registry。阶段 1 不能假设所有 Tool 都能在 Agent 之前静态生成。
- Extension 激活若从第一天就是异步 Interface，现有 TUI 的同步 `_select_provider()` 就必须改成异步启动状态；若为了少改代码把 open 设计成同步，阶段 2A 引入异步资源时会破坏 Interface。该取舍需要在详细设计中明确。
- `_select_provider()` 只从 `on_mount()` 和 provider 选择事件调用，二者都可在迁移批次中改成等待异步初始化；相关轻量 UI 测试通过子类覆盖该方法，迁移时必须同步调整测试替身。
- 现有 teammate 测试已经钉死角色能力：协作、文件、命令和任务板 Tool 必须存在，Agent/TeamCreate/TeamDelete 必须缺席。这可直接升级为 profile 契约测试。
- `resolve_agent_tools()`、`build_teammate_tools()` 和 `apply_coordinator_filter()` 都新建 Registry，却多数复用父 Registry 中同一个 Tool 对象；fork 只对 AgentTool 做浅复制。这不满足“每个 Agent 独立 ExtensionSession”的强隔离含义。
- in-process teammate 在 `AgentTool._execute_as_teammate()` 内部直接构造 Registry 和 Agent，然后把裸 Agent 交给 TaskManager；如果 Stage 1 要覆盖所有 teammate，TaskManager 或创建路径必须持有并关闭 child ExtensionSession，而不是只返回 Registry。
- Tool profile 需要区分两类：`owned` contribution（由该 Session 新建并负责注销）与 `borrowed` tool view（从父 Runtime 只读借用、不能由子 Session 关闭）。否则父子 Registry 的 Handle 会交叉删除。
- `TaskManager.BackgroundTask` 只持有裸 Agent；任务结束、失败或取消的 finally 只更新统计和通知，不关闭任何 Agent 级资源。让后台子 Agent 拥有独立 ExtensionSession 会同时要求引入可关闭的 Runtime lease。
- 前台 sub-agent 也直接运行裸 Agent 且没有 finally 清理；仅改 TaskManager 不能覆盖前台与 worktree 子 Agent。
- 因此 Stage 1 若同时追求“所有 Agent 独立 Session”和“小范围内置 Tool 切片”，会发生范围冲突。设计必须把完整独立 Runtime 与借用父 ToolView 的短生命周期 Agent 明确分层，并把消除 borrowed view 作为后续迁移条件。
- `CommandRegistry` 已证明冲突快速失败在项目中是可接受行为，但它没有注销或来源信息；Stage 1 只能借鉴冲突语义，不能把 CommandRegistry 顺手纳入迁移。
- `MCPManager.register_all_tools()` 直接逐个写 Registry；新 ToolRegistry 的重复冲突会使 MCP 冲突显性化。Stage 1 需要定义兼容诊断来源（如 `legacy`/`mcp:<server>`），但 MCP 连接与 client shutdown 所有权仍留在 MCPManager。
- `Agent` 构造函数只保存 Registry，不要求其中已经有 Tool；因此可以先创建空 Registry 和 Agent，再把二者放入 ExtensionContext，随后异步激活全部内置 Tool，一次解决 Tool 依赖 parent Agent 的环。
- 阶段 0 的 AgentLoop 每 Turn 都在运行时读取 `agent.registry`，所以 ExtensionSession 完成激活后不需要修改 Loop/ToolPipeline；这正是 Stage 1 应使用的稳定接缝。
- CLI prompt、Remote 和 teammate 都由 `__main__.py` 直接选择，TUI 由 App 管理；prompt 结束目前有多个早退分支，AgentRuntime 必须通过 `async with` 或统一 finally 才能保证 Session 关闭。
- Pi 官方扩展文档确认扩展工厂可以同步或异步，宿主会等待异步初始化完成后才继续 session startup；这支持 MewCode 从 Stage 1 起把 `open_session()` 设计为 async。
- Pi 的 Tool 诊断已经暴露 `sourceInfo`，并把内置、SDK 和扩展来源区分；MewCode 的 Contribution provenance 不是额外装饰，而是冲突诊断和未来用户可见工具清单的基础。
- Pi 的 ResourceLoader 负责发现并把扩展交给 AgentSession 创建流程；这再次支持 MewCode 把发现（后续 Stage 3）与 Session 激活/所有权（Stage 1）分开。
- 主设计的总测试表把后续阶段（资源、任务、事件、发现、信任、重载）混在一起；Stage 1 验收必须单列，只覆盖 Tool 注册/注销、关键扩展启动、profile、入口接线和 Session 隔离。
- 阶段 0 测试已经直接通过 ToolRegistry 接缝验证 Loop/Pipeline；Stage 1 新测试应保持这种层次：ExtensionHost Interface 测所有权，入口契约测 profile，现有 Loop/Pipeline 测试无需了解 ExtensionHost Implementation。
- 源码复核确认 TUI 交互提问 Tool 的真实名称是 `AskUserQuestion`，不是类名 `AskUserTool`；profile 契约必须使用 Schema 中的真实 Tool.name。
- prompt 入口确认仍有多个生命周期出口：它先用 `create_default_registry()` 注册基础与 ToolSearch，再构造 Agent 和依赖 Agent 的团队 Tool，coordinator 时还会替换 `agent.registry`；正常无 team 时直接 `return`，当前没有统一关闭所有者。
- `Agent` 已公开 `active_run`、`start_run()` 和 `cancel_active_run()`；Stage 1D 的 `AgentRuntime` 应委托这些公开生命周期能力，而不是复制 AgentRun 状态机。
- `Agent.start_run()` 已负责单活跃 Run、Run 创建、启动和完成后清空引用，`run()` 也完全经由该入口；Runtime 只需要在关闭时拒绝新 Run、取消当前 Run，并持有 Agent/Session，不应产生第二套运行状态。
- 当前 `builtins.py` 只有名称清单，`tests/test_runtime_composition.py` 也只锁定名称/顺序；下一条严格红灯应增加 typed bindings 与 Runtime close 行为，再实现 factory manifest。
- TUI 的内置 Tool 装配还夹带三类 Adapter 工作：基础 Tool 的 sandbox/file_history 注入、Skill loader/executor/catalog 与命令注册、以及 coordinator borrowed 过滤；Builtin manifest 只创建 Tool，入口仍负责这些 UI/Command/动态生命周期接线。
- Remote 与 prompt 的 lead Tool 共享 Agent/Team/Task/Trace/Worktree 依赖，但 Remote 额外有 `LoadSkill`，且 `TaskStop`/`SyntheticOutput` 的顺序不同；一个 typed `BuiltinRuntimeBindings` 可以承载具体依赖和 profile flags，manifest 必须按 profile 顺序逐项创建，不能复用无序集合。
- prompt tracer bullet 可以用真实 AgentLoop 和只替换 LLM 外部边界的测试验证：记录 `AgentRuntime.open()` 返回值，运行一次 end_turn，断言输出不变、Runtime 已 closed 且 owned Registry 为空；旧手工装配路径会因从未打开 Runtime 而明确红灯。
- prompt 已改为先创建 managers，再由 `AgentRuntime.open(PROMPT_LEAD)` 构造空 Registry/Agent/typed bindings；原事件循环包在 `async with runtime` 内，正常无 team 的早退也会关闭 Session。首次迁移测试与文件落盘存在短暂竞态，复跑后稳定通过，最终仍需全量与 diff 审计确认。
- TUI 当前在 `__init__` 就创建默认 Registry，`_select_provider()` 同步完成全部 Agent/Skill/Worktree/Team 装配，`on_mount` 与 provider 选择事件也都是同步；迁移需要把这三处形成可等待链，并把测试子类的同步 override 一并更新。
- TUI Runtime 迁移后，`SkillExecutor` 必须在 bindings factory 中创建，因为它同时依赖刚生成的 Agent；这样 LoadSkill 在 builtin activation 时就能拿到 loader/agent/executor，而入口仍负责 Skill catalog 与 slash command Adapter。
- TUI sandbox/file_history 现在作为 typed bindings 在 Tool factory 构造时注入；退出时 memory/Hook 先完成或取消，再 shutdown MCP，最后关闭 Runtime，保持旧业务清理且明确 Tool 所有权顺序。
- Remote 原先 `run()` 没有 finally，也没有 MCP/session 的统一关闭；迁移后 `_init_agent()` 成为 async，server boundary 的 finally 依次 shutdown MCP、Runtime 和 Session，初始化失败也不会跳过已建立资源的清理。
- ToolView 采用只读 snapshot 投影：按调用方给定顺序复用父 Tool 对象，但只创建本地 borrowed contribution，owner 标记原 runtime；关闭只撤销本地 projection handle，不持有或触碰父 Handle。teammate 的五个协作 Tool 作为 view-local additions 单独标源。
- MCP Manager 可从目标 Registry 的唯一 runtime identity 继承 runtime_id/generation，并以 `mcp.<server>` / `mcp:<server>` 标源；注册按 server 分批持有 Handle，因此冲突只回滚该 server，其他 server 仍可继续，shutdown 可精确注销动态 Tool。
- TUI 退出当前只并发清理 memory、Hook、MCP，再处理 stale task/team/session；Stage 1E 必须在 MCP shutdown 后补 Runtime close，同时让内存提取在 Agent/Tool Session 尚可用时完成。
- 详细设计钉死的 Runtime 外部面是 `open(request, extension_host=...)`、`start_run()`、`cancel_active_run()`、`aclose()` 和只读 `agent/diagnostics`；关闭责任是先拒绝新 Run、取消并等待 idle、再关闭 ExtensionSession，最终诊断残留 contribution。
- `OpenExtensionSession` 已把 profile 收在 `SessionContext` 中，当前实现没有重复的 `profile` 字段；Runtime request 应负责生成唯一 runtime_id/generation 并把同一主 Registry 同时交给 Agent 与 Host。
- 当前工作区已包含并验证了 TDD cycle 7 的 `AgentRuntimeRequest(agent_factory, bindings_factory)` 实现；目标测试 5 passed。它让入口只提供 Agent 构造与 typed bindings 构造，不再参与 Session/Registry 生命周期。
- 六个基础文件 Tool 共享同一个 `FileStateCache`，Write/Edit 还共享入口可选的 `file_history`；内置 factory 必须在每个 Runtime 内创建这份 cache，不能继续调用会立即注册 legacy contribution 的 `create_default_registry()`。
- Remote 的现有确切顺序是基础六个、ToolSearch、LoadSkill、Agent、TeamCreate、TeamDelete、TaskStop、SyntheticOutput；其 LoadSkill 需要在激活后连接 SkillLoader 与 Agent，适合由中央 factory 一次构造完成。
- TUI 当前在 `__init__` 就创建 legacy 基础 Registry，随后 `_select_provider()` 分散追加 12 个 Tool，并在 Tool 创建之间初始化 Skill/Worktree/Team 依赖；迁移必须先准备依赖，再让 Runtime 原子安装，而不能保留“先注册后补 setter”的半激活状态。
- 内置 Tool 的构造依赖是有限且可命名的：共享 file cache/history、protocol、Skill loader/executor/install callback、worktree manager、Agent/loader/task/trace/team/provider、fork/team flags、plan-mode callbacks，以及可选 Bash sandbox；适合一个固定字段的 `BuiltinRuntimeBindings`，不需要通用 DI 容器。
- ToolSearch 必须绑定 Runtime 主 Registry；LoadSkill/InstallSkill 当前只能用 setter 注入，但中央 factory 可以在注册前完成全部 setter，避免暴露半初始化 Tool。
- worker 协作 Tool 只额外需要 team manager、team_name、agent_id/agent_name；这些也应作为显式 bindings 字段，并按 profile 缺依赖时在启动阶段快速失败、由 Host 原子回滚。
- Runtime composition 测试现已覆盖四个 profile 的真实 Tool 实例、Schema 顺序、owner/runtime_id 和关闭清理；同文件还用最小真实 PromptClient 跑过 `_run_prompt()`，证明输出为 `prompt-ok` 且 Runtime/Registry 关闭，不需要再保留一份较弱的全 mock 入口测试。
- Textual 的两个 TUI 启动入口都是当前同步调用：`on_mount()` 的单 provider 分支和 `on_option_list_option_selected()`；二者都可改为 async handler 并 await `_select_provider()`，但 `tests/test_input_focus.py` 与 `tests/test_mascot_overlay.py` 的轻量子类替身也必须同步改成 async。
- TUI 退出已有 async `_cleanup()`：先并行 memory/hook/MCP，随后 stale worktree/team/session；Stage 1E 应在 MCP 完成后 `await runtime.aclose()`，并保持重复关闭安全，不能让 Runtime 与 MCP 同时竞态注销同一 Registry。
- TUI 可分两步安全迁移：先把 `_select_provider` 及两个 Textual 调用点改成 async（保持旧装配），用 UI 回归锁定初始化时序；再重排依赖并替换为 AgentRuntime，避免一次同时改变事件语义和工具所有权。
- TUI 迁移中间态已经把 App 初始 Registry 改为空并加入 `self.runtime`，但 `_select_provider` 仍引用被移除的 ToolSearch/AgentTool 导入；这是刻意短暂的红绿阶段，下一次编辑必须整体替换装配体后立刻编译/跑 UI 目标集，不能停在半迁移状态。
- TUI 完整 Runtime 装配现已把 SkillExecutor 放在 bindings factory 中创建：Agent 先拿空 Registry，SkillExecutor 再拿已创建 Agent，最后内置 Host 注册 LoadSkill/InstallSkill 等 Tool，解决原先 setter 注入与 Agent 构造的依赖环。
- Remote 当前代码也已完成同形迁移：`_init_agent()` 是 async，使用 REMOTE_LEAD Runtime；`run()` 用 finally 调 `_shutdown()`，且 shutdown 明确先 MCP、再 Runtime、最后 Session。下一步需要真实 Adapter 测试固定 profile/owner 与顺序，而不是继续改生产结构。
- `ToolView` 及其公开契约已在当前工作区：它为选中的父 contribution 建立仅属于 View 的 borrowed 投影，owner 记录 `borrowed_from`，自身 disabled/discovered 独立，register 被封为 read-only，幂等 close 只清空投影、不触碰父 Handle。
- `agents/tool_filter.py` 尚未使用 ToolView，四条路径仍新建普通 legacy Registry；下一步只需把过滤结果改成 names/replacements/additions 参数，不改变现有筛选规则或 Tool 对象复用行为。
- 当前权威代码已完成四个 ToolView Adapter 的替换（上一条是替换前快照）；但 `build_teammate_tools()` 若父视图已含 TaskCreate 等协作名，会同时借用并追加本地 Tool，引发显式冲突。应先从 borrowed names 排除五个 coordination Tool，让 child-local 实现明确覆盖旧静默覆盖语义。
- external teammate Runtime 已补齐 SkillLoader，避免 profile 中 LoadSkill/InstallSkill 只是“有名字但未初始化”；worker 的 MCP 仍是动态 owner，并在 Runtime 之前 shutdown，符合 Stage 1 边界。
- teammate ToolView 的同名 coordination 冲突已通过先排除父 projection 修复；既有 silent overwrite 被替换为显式 child-local owner，同时保持工具清单与行为。
- MCPManager 当前把 `connect_all()` 的 flat Tool 列表逐个 legacy-register，既不保存 Handle 也不记录 server provenance；shutdown 只关 client，所以 Runtime 关闭前 MCP contribution 会残留并被误报为泄漏。
- MCP 注册适合由 Manager 做一个 registration transaction：从 wrapper 的 server name 生成 `mcp.<server>` owner，继承目标 Registry 唯一的 runtime_id/generation；任一注册冲突反向关闭本批 Handle并写入 ConnectResult.errors，成功则保存 Handle，shutdown 先注销再关 client。
- MCP 当前实现选择“每个 server 一个注册事务”而非所有 server 全有或全无：同一 server 的第 N 个 Tool 冲突会回滚该 server 已注册 Tool，其他 server 保持可用，符合既有部分失败容错语义；Manager shutdown 再反向关闭全部成功 Handle。
- 生产入口的 `registry.register(...)` 已清零；剩余注册只在 ExtensionHost、MCPManager、MemoryConsolidator 的隔离小 Registry 和 legacy `create_default_registry()` 工厂内部，下一步要判断后两者是否是生产入口重复装配或合法内部兼容面。
- 完成审计对照 17.2 发现仍需补强证据：双 Runtime 隔离、prompt 异常关闭、TUI 重复/并发 provider 初始化只保留一个 Runtime、external teammate cancel finally，以及 Session 某个 close callback 失败仍执行其他清理。现有实现部分可由代码推断，但完成门要求直接行为证据。
- 主设计与阶段 1 详细设计的状态段仍写“等待评审/实施前审批门未勾选”，已与当前用户授权和实现事实过时；最终必须更新为已批准、已实施和验证结果，避免文档继续引导重复实施。
- AgentRuntime 当前关闭 Session 后没有记录残留 contribution，未完全满足设计 11.3 的泄漏诊断步骤；应保留不属于 Runtime 的残留 Tool，但把 name/owner/source 追加到公开 diagnostics，避免越权删除动态或 legacy owner。
- 最终结构搜索通过：四个入口没有 `create_default_registry()` 或 Tool `registry.register()`；只剩 AgentNameRegistry 名字登记。ExtensionAPI 没有提前增加 Command/Event/Resource/Service，四个过滤 Adapter 都使用 ToolView，MCPManager 保存并反向关闭 Handle。
- Git stat 显示 `__main__.py` 与 `tool_filter.py` 因此前 LF 归一化呈现整文件差异；需要恢复它们原有 CRLF 风格以缩小 patch，同时保持混合行尾问题不复发。
- TUI 源码审计发现 `_select_provider_unlocked()` 已实现“先验证新 client，再关闭旧 Runtime并重建 provider-scoped manager”；后来加锁 wrapper 曾重复提前清理，已删去重复逻辑。现在 lock 只负责串行化，具体事务仍由 unlocked 实现，认证失败不会先杀死旧 Runtime。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 使用 `codebase-design` 的 Module、Interface、Seam、Adapter、Depth、Leverage、Locality 术语 | 保持阶段 1 的模块边界可验证，而不是只画抽象架构图 |
| 不复用 Mini Plugin Agent 教学模块作为生产实现 | 它的范围与阶段 1 需要解决的多 Agent、异步资源、MCP 和隔离语义不同 |
| 阶段 1 采用 Tool-only 的纵向切片 | 先让真实调用方穿过 ExtensionHost 接缝；Command、事件、通用资源和后台任务保留到后续阶段，避免浅抽象铺满仓库 |
| `ExtensionSession` 内部使用 AsyncExitStack，但 Stage 1 不公开通用 ResourceScope | 获得原子回滚和反向注销，同时不抢跑 Stage 2A 的接口承诺 |
| 以显式 Tool profile 取代“所有入口同一清单”的模糊要求 | TUI、prompt、Remote、lead、teammate 本来就有不同交互能力；统一的是装配规则和来源，不是机械同表 |
| Stage 1 只托管 ExtensionSession 拥有的主 Registry 注册 | MCP 连接、UI 清理和派生过滤 Registry 暂由现有所有者管理，后续阶段再迁移，避免所有权交叉 |
| 所有 Stage 1 内置 Tool 在 Agent 构造后一次原子激活 | Agent 可先持有空 Registry；这样不需要暴露“两阶段激活”Interface，依赖 Agent 的 Tool 也能正常构造 |
| `ExtensionHost.open_session()` 与 AgentRuntime 创建保持 async | 避免 Stage 2A 加入异步资源时破坏外部 Interface；TUI 初始化作为明确迁移批次改成异步等待 |
| Stage 1 明确区分独立 Runtime 与派生 ToolView | root、Remote、外部 teammate 拥有独立 Session；短生命周期 sub-agent/fork 暂可借用父贡献的只读视图，但不伪装成自己拥有这些注册 |
| 不在 Stage 1 给裸 Agent 塞隐式 close callback | 资源所有权应由 AgentRuntime/ExtensionSession 显式表达；隐藏回调会让 TaskManager 和前台调用方继续看不见生命周期 |
| ToolRegistry 内部注册对象结构化，现有查询 Interface 保持不变 | `get/list_tools/get_all_schemas` 继续返回 Tool，所有权与来源只通过新诊断 Interface 暴露，减少调用方迁移面 |
| 先构造空 Registry + Agent，再打开 ExtensionSession | 避免引入两阶段 Extension activation 或复杂依赖图；所有 Tool 仍在首次 Run 前原子完成注册 |

## Current Problem Matrix
| Problem | Current evidence | Stage 1 design rule |
|---------|------------------|---------------------|
| 重复装配 | `app.py`、`remote.py`、`__main__._run_prompt()`、`_build_teammate_registry()` 各自注册 Tool | 一个内置 Tool manifest，入口只选择 profile 和提供 bindings |
| 静默覆盖 | `ToolRegistry.register()` 直接赋值 | 同名注册抛出带 existing/attempted 来源的结构化错误 |
| 无法撤销 | `register()` 返回 `None`，Registry 无 unregister | 每次成功注册返回幂等 Handle，按 token/identity 精确撤销 |
| 部分启动 | 第 N 个 Tool 失败时前 N-1 个仍保留 | 每个扩展单独 AsyncExitStack，关键扩展失败再回滚整个 Session |
| Agent 依赖环 | Agent 需要 Registry，若干 Tool 又需要 parent Agent | 空 Registry 创建 Agent，首次 Run 前一次异步激活全部内置 Tool |
| 角色清单漂移 | 四个入口的 Tool 集不同且手工维护 | `ToolProfile` 固定确切名称和顺序，入口契约测试锁定 |
| 父子所有权混淆 | 过滤 Registry 复用父 Tool 对象 | owned Session 与 borrowed ToolView 分开，borrowed view 不持有父 Handle |
| 生命周期缺口 | prompt、worker 和 TaskManager 只持有裸 Agent | root Runtime 必须 `async with`/finally；短生命周期子 Agent 的完整 lease 迁移另列后续条件 |
| 动态 Tool 来源缺失 | MCP 直接向 Registry 注册 | Stage 1 Registry 支持来源；MCP 仍由 MCPManager 持有，迁移时保存自己的 Handle |
| 终局范围过大 | 主设计把 Command、事件、资源、任务、发现、重载都列入 Host | Stage 1 ExtensionAPI 只有 `register_tool()` 和只读 SessionContext |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 当前工作区包含阶段 0 实现与用户既有未跟踪内容 | 只读盘点；设计文档单独新增或更新，不覆盖无关文件 |
| 本轮中途 Git 分支和阶段 0 提交状态由外部改变 | 只读确认当前 HEAD 和状态，不切换、不提交、不重置；以 `6578fa6` 作为最终阶段 1 基线 |

## Resources
- `docs/mewcode-pi-inspired-runtime-design.md`
- `docs/mewcode-agent-loop-stage0-design.md`
- `.planning/2026-08-16-mewcode-pi-inspired-runtime-design/`
- https://books.antinomie.org/pi/chapter/01
- https://books.antinomie.org/pi/chapter/02
- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md
- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md
