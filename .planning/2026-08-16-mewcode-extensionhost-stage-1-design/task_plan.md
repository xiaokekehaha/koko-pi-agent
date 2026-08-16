# Task Plan: MewCode ExtensionHost 阶段 1 设计与实施

## Goal
在阶段 0 的唯一 AgentLoop、ToolPipeline 与 AgentRun 基础上，按已评审设计完成 ExtensionHost 的 Stage 1A-1F 实施，并通过行为、Interface、入口和全量回归验证。

## Next Step
Stage 1 已完成并验证；后续阶段需重新评审范围和授权。

## Current Phase
Complete - Stage 1A–1F implemented and verified

## Scope
- 主体：当前 MewCode 产品；Pi 只作为 ExtensionHost、ExtensionSession 与 ResourceLoader 的参考。
- 设计对象：ExtensionHost、ExtensionCatalog、ExtensionSession、ExtensionAPI，以及它们与 AgentRun/AgentLoop/ToolPipeline 的接缝。
- 产物：阶段 1 详细设计文档、planning-with-files 的发现和进度记录、分批迁移与验收计划。
- 非目标：建立 Mini Pi 平行框架、引入通用依赖注入容器、开放不受信任的第三方代码沙箱、提前实施阶段 2 的 Command/资源/事件/重载能力。
- 实施授权：用户已明确要求“开始开发，直到完成和验证成功”，Stage 1A-1F 的生产代码边界已解除。

## Phases

### Phase 1: 基线恢复与需求确认
- [x] 恢复阶段 0 计划、主设计与当前 Git 状态
- [x] 查询相关项目记忆并以当前仓库为准校验
- [x] 明确阶段 1 的目标、非目标、兼容约束和审批门
- **Status:** complete

### Phase 2: 现有扩展路径与所有权盘点
- [x] 跟踪 Tool、Command、Hook、Skill、MCP 的注册与调用路径
- [x] 跟踪 CLI、Remote、主 Agent、队友 Agent 的组合与关闭路径
- [x] 建立当前问题矩阵：重复装配、冲突、回滚、资源和诊断
- **Status:** complete

### Phase 3: ExtensionHost 深模块设计
- [x] 定义唯一外部 Interface 和内部模块职责
- [x] 定义 Catalog、Session、API 的所有权、状态机与生命周期
- [x] 定义冲突策略、原子安装、失败回滚、反向清理与后台任务边界
- [x] 用删除测试、Interface 测试面和依赖分类验证 Depth
- **Status:** complete

### Phase 4: Runtime 集成与兼容设计
- [x] 定义与 AgentRuntime、AgentRun、AgentLoop、ToolPipeline 的精确接缝
- [x] 定义 Tool、Command、Hook、Skill、MCP 适配顺序和旧入口兼容策略
- [x] 定义主 Agent、队友 Agent、Remote 和 headless 的隔离语义
- **Status:** complete

### Phase 5: 分批迁移与验证计划
- [x] 拆成可独立合并、验证和回滚的 Stage 1A-1F
- [x] 为每批列出文件影响、行为变化、测试和退出条件
- [x] 定义观测性、性能、安全与兼容验收矩阵
- **Status:** complete

### Phase 6: 文档校验与交付
- [x] 创建并复核阶段 1 详细设计文档
- [x] 同步主路线状态与文档链接，但不修改生产代码
- [x] 校验链接、术语、Mermaid、工作区边界和 planning 文件完整性
- **Status:** complete

### Phase 7: Stage 1A 行为刻画与实施基线
- [x] 复核当前分支、HEAD、工作区、AGENTS/CONTEXT 和测试命令
- [x] 固定四个 ToolProfile 的名称、顺序和角色差异
- [x] 写 ToolRegistry 静默覆盖的预期红灯测试并确认失败原因
- [x] 记录生产入口、动态 MCP 与派生 Registry 的当前所有权基线
- **Status:** complete

### Phase 8: Stage 1B ToolRegistry Contribution 与 Handle
- [x] 逐个 TDD 实现 ContributionOwner、ToolContribution、RegistrationHandle 和 ToolConflictError
- [x] 保持 get/list/schema/deferred/enable/disable 兼容并支持来源诊断
- [x] 实现精确幂等注销和 disabled/discovered 清理
- [x] 运行 Registry 与既有 Tool/Agent 目标测试
- **Status:** complete

### Phase 9: Stage 1C ExtensionHost 事务核心
- [x] TDD 实现 Catalog、SessionContext、Diagnostic 和结构化错误
- [x] 实现 async open_session、ExtensionAPI.register_tool 和单扩展部分失败回滚
- [x] 实现多扩展 critical 失败反向回滚、API 失效和幂等关闭
- [x] 只通过 Host/Session Interface 验证，不测试私有 scope
- **Status:** complete

### Phase 10: Stage 1D 内置 manifest、AgentRuntime 与 prompt tracer bullet
- [x] TDD 固定四个有序 ToolProfile 与 typed bindings
- [x] 实现空 Registry + Agent + 原子 ExtensionSession 的 AgentRuntime
- [x] 先迁移 prompt 到 async Runtime 生命周期并删除其手工内置装配
- [x] 验证 prompt profile、Schema、AgentRun 和关闭后 owned contribution
- **Status:** complete

### Phase 11: Stage 1E TUI 与 Remote Adapter 迁移
- [x] 把 TUI provider 初始化接入可等待的 AgentRuntime
- [x] 迁移 TUI/Remote 内置 Tool 装配与关闭顺序
- [x] 保持 Skill、Permission、Hook、MCP、cancel 和 UI 行为
- [x] 运行 TUI/Remote 目标回归测试
- **Status:** complete

### Phase 12: Stage 1F teammate、ToolView、MCP 与旧路径删除
- [x] external teammate 使用独立 TEAMMATE_WORKER Runtime
- [x] coordinator/sub-agent/fork 使用 borrowed ToolView 且不拥有父 Handle
- [x] MCPManager 保存来源和 Handle，失败与 shutdown 反向注销
- [x] 删除生产入口的重复内置注册与不再需要的默认装配路径
- **Status:** complete

### Phase 13: 全量验证与完成审计
- [x] 运行 Stage 1 Interface/入口矩阵、阶段 0 回归和全量 pytest
- [x] 运行 Ruff、compileall、git diff --check 和结构搜索
- [x] 按详细设计逐项审计目标、非目标、验收门和残留所有权
- [x] 更新两份设计文档和 planning 结果，确认没有无关文件被覆盖
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 使用独立阶段 1 计划目录 | 保留已完成的阶段 0 证据，并让本轮设计可独立恢复和审计 |
| ExtensionHost 必须是深模块 | 调用方只学习少量 Interface，发现、注册、所有权、回滚、清理和诊断复杂度留在实现内部 |
| 本轮不修改生产代码 | 用户明确要求先做阶段 1 设计和规划 |
| 不使用并行子 Agent | 当前任务未要求委派，且接口决策需要由一个连续上下文保持一致 |
| Stage 1 ExtensionAPI 只有 `register_tool()` | 先证明 Tool 所有权纵向切片，避免 Command、事件、资源和任务形成浅 Interface |
| 四个入口使用显式 ToolProfile | 保持现有角色差异、名称和顺序，同时统一 factory、来源和回滚规则 |
| 短生命周期子 Agent 使用 borrowed ToolView | 明确当前共享 Tool 对象的过渡语义，不把它误报成独立 Session，也不扩大 Stage 1 到 TaskManager lease 重构 |
| TDD seam 使用设计文档已确认的四个 Interface | 用户在详细设计后明确授权开发；测试只经过 ToolRegistry、ExtensionHost/Session、AgentRuntime 和 ToolView/profile 的公开 Interface |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| 暂无 | - |
| 两次追加实施基线时混用了 findings/task_plan/progress 的 patch 锚点 | 停止猜测锚点，读取准确行号后分别更新三个文件；未影响生产文件 |
| `uv run pytest` 无法读取沙箱外 `~/.cache/uv/sdists-v9/.git` | 不申请越权且不重复 uv 命令；改用项目现有 `.venv/bin/pytest` 运行同一测试集 |
| 首次创建 profile 测试时误发了空 Update hunk | 立即改为完整 Add File patch；未创建或修改任何文件 |
| Host 首个 green 一次实现了 critical partial rollback，导致下一条回滚测试没有先红 | 保留该必要行为和覆盖，记录 TDD 偏差；后续 Runtime/入口切片恢复严格 red-first，不再提前实现未测行为 |
| 并行读取两个源码片段时 `Too many open files (os error 24)` | 停止并行启动子进程，改为单个顺序命令读取，避免重复相同失败 |
| 较大的顺序读取命令再次触发同一文件描述符上限 | 改为每次只执行一个小型只读命令；若仍失败则检查当前终端进程状态后重新规划 |
| 非关键 `pyproject.toml` 合并读取第三次触发文件描述符上限 | 执行 3-strike broader rethink：停止读取非必要信息，继续使用已验证的 Python 3.11/pytest 项目证据，最终校验拆成最小命令 |
| 按旧行号整体替换 TUI 装配体时误吞 `_resolve_context_window` 与 provider 事件方法 | 新的真实 TUI Runtime 测试立即以 AttributeError 暴露；恢复两个 async 方法和 UIController 分隔，目标测试 `2 passed` |
