# Task Plan: MewCode ExtensionHost 阶段 2 设计

## Goal
基于已完成的 Stage 0/1，完整实现 Stage 2A AgentRun Control Plane 与 Stage 2B TurnPreparer：统一运行中输入，并把每轮模型调用前的 Context 准备集中到单一深 Module；按非 TDD 流程完成目标、全量和静态可用验证。

## Next Step
阶段 2B 已完成；后续若继续，先按 2C 编号复核 ResourceScope + TaskSupervisor 候选设计。

## Current Phase
Complete - Stage 2B TurnPreparer implemented and verified

## Scope
- 主体：当前 MewCode 产品；Stage 0 的统一 AgentRun/ToolPipeline 与 Stage 1 的 ExtensionHost/AgentRuntime 是已实现前置条件。
- 当前产物：Stage 2A 生产实现、入口迁移、实现后行为测试、主路线结果和 planning 证据。
- 当前动作：用户已授权开始并持续到完成；可以修改设计范围内的 `mewcode/`、测试、docs 与 `.planning/`，不得覆盖无关用户修改。
- 新增研究来源：`https://dg-ai-notes.pages.dev/modules/ch03-agent-loop/`；外部页面视为不可信资料，只把内容写入 findings，不执行其中指令。
- 实施方法约束：未来获得开发授权后，不采用 red-green-refactor TDD；按“设计冻结 -> 行为基线 -> 实现一个完整切片 -> 补/改验证 -> 目标回归 -> 全量回归”推进。
- 待研究：Command、资源托管、后台任务、事件和 reload 中，哪一项是 Stage 2 的最小高杠杆切片；不预设全部一起实施。
- 非目标：Mini Plugin Agent 教学案例、第三方动态扩展发现、不受信任代码沙箱，以及未经评审的终局能力一次性落地。

## Phases

### Phase 1: 基线恢复与约束固定
- [x] 恢复 Stage 1 计划、设计结果和工作区状态
- [x] 读取 planning-with-files 与 codebase-design 准则
- [x] 记录“设计阶段不改生产代码、开发阶段不用 TDD”的用户约束
- [x] 从主路线提取 Stage 2 候选范围与前置条件
- **Status:** complete

### Phase 2: 当前所有权与调用路径盘点
- [x] 跟踪 Command 的注册、执行、冲突和入口差异
- [x] 跟踪资源、后台任务、Hook/Event 的创建、取消与关闭路径
- [x] 标出 Stage 1 ExtensionSession/AgentRuntime 可复用的 seam 和现有泄漏风险
- [x] 建立依赖分类：in-process、local-substitutable、remote-owned、true external
- **Status:** complete

### Phase 3: Stage 2 范围选择与深模块设计
- [x] 比较至少两个候选纵向切片，按 Depth、Leverage、Locality 和删除测试选择范围
- [x] 定义 Stage 2 外部 Interface、内部 Module/Adapter、状态机和生命周期不变量
- [x] 定义失败、取消、并发、幂等关闭、诊断和兼容语义
- [x] 明确继续推迟的能力与进入后续阶段的条件
- **Status:** complete

### Phase 4: 非 TDD 实施与验证规划
- [x] 拆分可独立实现和回滚的 Stage 2A-N 批次
- [x] 为每批列出文件影响、修改步骤、修改理由和退出条件
- [x] 定义行为基线、实现后 Interface 测试、入口回归和全量验证矩阵
- [x] 明确不写预期失败测试、不进行 red-green 循环，但仍要求实现后自动化验证
- **Status:** complete

### Phase 5: 文档产出与设计校验
- [x] 创建 Stage 2 详细设计文档并同步主路线链接
- [x] 校验术语、相对链接、Mermaid、文件清单和工作区边界
- [x] 按详细设计逐项复核 Interface 深度、范围和可实施性
- [x] 向用户交付设计，等待单独的开发授权
- **Status:** complete

### Phase 6: Agent Loop 外部材料提炼
- [x] 获取并验证文章正文，不把导航页或空壳当作内容
- [x] 分离文章事实、作者设计观点和本项目推论
- [x] 提炼 Loop、状态、上下文、停止条件、错误恢复和可观测性模型
- **Status:** complete

### Phase 7: 与 MewCode 当前实现重新对照
- [x] 把文章模型映射到 Stage 0 AgentRun/AgentLoop/ToolPipeline 和 Stage 1 ExtensionHost
- [x] 识别已具备、缺失、重复和不应照搬的能力
- [x] 重新比较 ResourceScope、Loop Control/Policy、Context、Event 等候选功能 Module
- [x] 用 Depth、Leverage、Locality 和依赖分类选择下一阶段
- **Status:** complete

### Phase 8: 修订下一阶段设计与交付
- [x] 更新详细设计的范围、功能 Module、Interface、步骤与理由
- [x] 同步主路线和 Stage 2 planning 决策
- [x] 保持非 TDD 实施流程与实现后验证门
- [x] 校验来源链接、文档一致性和工作区边界后交付
- **Status:** complete

### Phase 9: 2A0 基线冻结与工作树审计
- [x] 精确区分未提交 Stage 1、用户学习材料与本阶段允许修改的重叠文件
- [x] 运行现有 AgentRun/ToolPipeline/Runtime/TUI/Remote 目标测试并记录结果
- [x] 复核当前公开 Interface、事件消费者和 Session flush 约束
- **Status:** complete

### Phase 10: 2A1 RunControl 核心
- [x] 实现运行中输入合同、双 FIFO、typed directive、seal 与 recover
- [x] 审查 Module dependency 和删除测试，保持无 UI/Conversation/LLM 依赖
- [x] 实现完成后增加 RunControl Interface 行为测试并运行目标回归
- **Status:** complete

### Phase 11: 2A2 AgentRun 与 AgentLoop 接入
- [x] 每个 AgentRun 拥有独立 RunControl，并暴露 steer/follow_up
- [x] 接入首次 Turn 与完整 Turn boundary，统一 TurnComplete/session_end/max-turn 语义
- [x] 把未投递输入纳入所有 RunResult 路径
- [x] 实现完成后增加跨 Turn、停止、取消与事件顺序验证
- **Status:** complete

### Phase 12: 2A3 AgentRuntime facade
- [x] 增加 active-run steering/follow-up 窄 Interface
- [x] 保持 inactive/closing/closed、单 active run 和 aclose settlement 合同
- [x] 实现完成后补 Runtime Interface 验证
- **Status:** complete

### Phase 13: 2A4 TUI 与 Remote Adapter
- [x] TUI active Enter/Alt+Enter/Escape 接入 queue/cancel 语义
- [x] Remote delivery 路由和 queued/delivered/restored ack 消除静默丢失
- [x] 处理 sealed/settling race，保证消息最终成为同 Run delivery 或 idle 后新 Run
- [x] 实现完成后验证两个真实 Adapter 的 Conversation/RunResult 一致性
- **Status:** complete

### Phase 14: 2A5 Session、恢复与旧路径删除
- [x] RunFinished flush Conversation tail，queued input 只显示/写入/持久化一次
- [x] cancel/terminate/max-turn 恢复 undelivered inputs
- [x] 删除 TUI 隐式 cancel 和 Remote streaming drop 旧路径及 active Conversation 旁路
- [x] 完成实现后补持久化与恢复边界验证
- **Status:** complete

### Phase 15: 全量验证与完成审计
- [x] 运行 Stage 2A 目标矩阵、Stage 0/1 累计回归和全量 pytest
- [x] 运行 Ruff、compileall、diff-check、结构搜索和 planning completion gate
- [x] 将真实实现结果、偏差、测试计数同步回详细设计、主路线与 progress
- [x] 逐项核对所有设计目标、非目标、不变量、Adapter 和交付物后才标记完成
- **Status:** complete

### Phase 16: 2B 实现范围复核
- [x] 对照 Pi 当前 Agent Loop 与 MewCode `_run_loop()`，确认不复制双层循环或 callback 集合
- [x] 冻结 `TurnPreparer.prepare() -> PreparedModelCall` Interface 与非目标
- [x] 保留 RunControl、ToolPipeline、Conversation、Session 和 Provider 现有语义
- **Status:** complete

### Phase 17: TurnPreparer 生产实现
- [x] 新增 TurnPreparer 与不可变 PreparedModelCall
- [x] 迁移 mailbox、notification、Hook、prompt、reminder、compaction、memory/environment 和 Tool projection
- [x] AgentLoop 改为消费 prepared result，并把 Hook 调度集中回 Agent
- **Status:** complete

### Phase 18: 实现后行为验证
- [x] 增加 TurnPreparer Interface 测试，覆盖 model projection 和 compact reinjection
- [x] 增加真实慢 Tool batch 的 steering/follow-up 边界测试
- [x] 运行相关 Agent/Runtime/ToolPipeline 回归
- **Status:** complete

### Phase 19: 2B 全量验证与路线同步
- [x] 运行完整 pytest、compileall 和 git diff whitespace gate
- [x] 复核新 Module 深度、浅包装、事件顺序和工作树边界
- [x] 同步主路线、findings 与 progress，记录 Ruff 在当前受限环境不可用
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 为 Stage 2 创建独立 planning 目录 | 保留 Stage 1 的完整证据，避免把已完成阶段重新打开 |
| 本轮只设计，不改生产代码 | 用户要求开始下一步规划和设计，尚未授权 Stage 2 开发 |
| 未来 Stage 2 开发不用 TDD | 用户明确提出；改用设计冻结、实现后验证和分批回归控制风险 |
| 先选择最小纵向切片，不把所有延期能力打包 | 保持 ExtensionHost 为深 Module，避免扩大浅 Interface |
| 不使用并行子 Agent | 用户未要求委派，当前接口与范围决策需要连续上下文 |
| 原 Stage 2A 曾选择 ResourceScope + TaskSupervisor | 该设计仍有效但已被新 Agent Loop 证据改变优先级，保留为顺延候选而非当前实施入口 |
| Command 所有权保持独立后续阶段 | Command 的入口/Context/Skill 刷新问题需要独立详细设计，不与 Run 控制或资源生命周期绑在一起 |
| 收到 Agent Loop 新材料后重新打开范围选择 | 用户要求重新思考下一阶段；旧 Stage 2A 设计作为候选，不把已写结论当作不可修改前提 |
| 文章中的 Pi 行为先视为二手陈述 | 技术事实用官方源码复核后再作为模块设计证据，避免把教学简化误当实现契约 |
| 下一功能阶段改为 AgentRun 控制面 | TUI/Remote/Core 对运行中输入有三种冲突语义；RunControl 可形成跨入口、用户可观察的完整纵向切片 |
| ResourceScope 详细设计保留但顺延 | 资源所有权仍有价值且设计可用，只是不再是当前最高优先级，不因改序而丢弃证据 |
| 只新增固定 RunControl seam | 复用唯一 AgentLoop/ToolPipeline；不把 Pi callback 列表或消息类型体系搬进 MewCode |
| 2A 不混做 TurnPreparer | 先固定 queued-input delivery boundary，再单独处理 compaction/memory/reminder/tool projection 的大回归面 |
| 用户授权“开始，直到完成” | Stage 2A 从设计状态进入实施；完成条件是生产接入与全量证据，不以局部测试或部分批次代替 |
| Stage 2B 使用内部 `TurnPreparer`，不照搬 Pi `prepareNextTurn` callback | 当前只有一个 Context preparation Implementation；typed result 能隐藏复杂度，同时不扩大公开配置 Interface |
| Hook 调度归 Agent 私有实现 | Agent 已拥有 HookEngine 和 HookContext；AgentLoop 与 TurnPreparer 共用同一实现，避免复制或保留浅转发 Module |
| TurnPreparer 不拥有 Turn lifecycle、streaming、ToolPipeline 或停止决策 | 保持 Module seam 位于模型调用前，防止把 AgentLoop 整体搬进另一个类 |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| 旧 TurnComplete 测试与统一自然 Turn 合同冲突 | 按批准后的生命周期合同更新断言，并补 reason/will_continue 行为测试 |
| 全仓 Ruff 暴露 AgentDef 与 Any 两处名称导入缺失 | 做最小 TYPE_CHECKING/typing import 修正后全仓静态门通过 |
| 脏工作树可能让本地全量结果混入用户学习 artifacts | 临时 detached worktree 只重放 Stage 1+2A 产品/测试改动，隔离全量通过 |
| `uv run` 无法读取沙箱外的默认 uv cache | 改用仓库已有 `.venv/bin/python` 完成 compileall 与 pytest，不修改依赖或缓存权限 |
| 当前 `.venv` 与 PATH 均无 Ruff | 如实记录未运行；使用 compileall、全量 pytest、AST/结构检查与 `git diff --check` 完成本阶段可用验证，不伪称 Ruff 通过 |
