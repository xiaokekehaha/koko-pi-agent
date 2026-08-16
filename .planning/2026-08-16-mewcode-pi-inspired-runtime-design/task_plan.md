# Task Plan: MewCode Runtime 参考 Pi 的迭代设计

## Goal
在当前 MewCode 项目上完成 Pi-inspired Runtime 设计，并落地阶段 0：唯一 AgentLoop、唯一 ToolPipeline、AgentRun 生命周期与统一 Adapter；不创建 Mini Pi 平行框架。

## Next Step
阶段 0 已完成；下一阶段是 ExtensionHost，但需要作为独立开发阶段重新确认范围。

## Current Phase
Complete - Stage 0 implementation and verification

## Scope
- 主体：当前 `mewcode` 包、CLI、Remote、主 Agent 与队友 Agent。
- 参考：Pi 的 AgentSession、ExtensionAPI、ResourceLoader、事件和 Session 生命周期。
- 产物：主设计文档、调研发现、执行记录和后续实施阶段计划。
- 非目标：实现 Mini Pi、改变 Session/Tool Schema/用户配置、在阶段 0 同时引入 ExtensionHost 或 Cordis 全套运行时。
- 实施授权：用户在设计评审后明确要求“开始开发，直到完成”，阶段 0 的生产代码边界已解除。

## Phases

### Phase 1: 目标校正与现状发现
- [x] 确认主体是当前 MewCode，Pi 只是架构参考
- [x] 检查仓库分支、未跟踪文件和现有扩展点
- [x] 阅读 Pi、Python 标准库与 pluggy 的一手资料
- [x] 把发现写入 `findings.md`
- **Status:** complete

### Phase 2: 架构设计文档
- [x] 建立 MewCode Runtime 总体架构
- [x] 设计 AgentRuntime、ExtensionHost、ExtensionSession 与 ExtensionAPI
- [x] 删除或修正所有可能暗示“实现 Mini Pi”的措辞
- [x] 复核与当前 Tool、Command、Hook、Skill、Team、Remote 的映射
- **Status:** complete

### Phase 3: 分阶段实施规划
- [x] 把实施拆成可独立合并和回滚的纵向阶段
- [x] 为每阶段列出文件影响、Interface 变化和兼容策略
- [x] 明确不实施生产代码的审批门
- **Status:** complete

### Phase 4: 设计验证
- [x] 检查文档链接、术语和 Mermaid 结构
- [x] 对照当前仓库再次验证设计假设
- [x] 记录设计验证结果，不把现有未跟踪 Demo 当成已批准实现
- **Status:** complete

### Phase 5: 评审交付
- [x] 汇总关键决策、风险和待用户确认项
- [x] 给出主设计文档与规划文件入口
- [x] 停在实施审批门前
- **Status:** complete

### Phase 6: Pi 第 1、2 章复核与代码路径对照
- [x] 阅读 Pi 的 core / Agent / Harness 分层
- [x] 跟踪一次 prompt、Turn、Tool 与事件的完整路径
- [x] 对照 MewCode 的 `run()`、`run_to_completion()` 与 Tool 执行路径
- [x] 把外部阅读发现写入 `findings.md`
- **Status:** complete

### Phase 7: 阶段 0 深模块设计
- [x] 定义唯一 Agent Loop 的 Interface、状态输入和事件输出
- [x] 定义 Tool prepare → execute → finalize 管线与截断安全规则
- [x] 定义 active run、取消、settlement 与后台任务所有权
- [x] 定义 interactive / non-interactive Adapter 的职责
- [x] 通过删除测试和 Interface 测试面验证模块深度
- **Status:** complete

### Phase 8: 主路线与实施规划修订
- [x] 在主设计中插入阶段 0，并调整后续阶段编号与依赖
- [x] 给出文件影响、迁移顺序、兼容策略和回滚点
- [x] 保持 ExtensionHost 设计有效，但不让它固化当前双轨循环
- **Status:** complete

### Phase 9: 设计验证与交付
- [x] 复核代码证据、文档链接、术语和 Mermaid
- [x] 检查生产源码仍未修改
- [x] 运行文档级校验并记录结果
- [x] 停在新的实施审批门前
- **Status:** complete

### Phase 10: 阶段 0 实施与完成审计
- [x] 建立类型化 Runtime events 和兼容导出面
- [x] 实现唯一 ToolPipeline，统一 Hook、Permission、参数校验、并发、截断保护、spill、budget 与 recovery
- [x] 实现唯一 AgentLoop 和 AgentRun，统一 streaming、Remote sink 与 headless Adapter
- [x] 删除旧 StreamingExecutor、三条私有 Tool 路径和第二份 headless while Loop
- [x] 迁移 TUI、Remote、Skill、TaskManager、AgentTool、teammate 与非交互入口到兼容 facade 背后的同一 Run
- [x] 增加 Interface 级安全测试并完成全量测试、Ruff、编译和结构搜索审计
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 当前 MewCode 是唯一产品主体 | 用户明确要求参考 Pi 来迭代当前项目，而不是实现 Mini Pi |
| 保留现有 Agent Loop | 当前循环、工具执行、团队和 Remote 已有真实能力，重写会扩大风险 |
| 采用每个 Agent 独立 ExtensionSession | 当前项目存在主 Agent 和队友 Agent，需要默认隔离状态与资源 |
| 先设计、后实施 | 用户先要求理解模块和理由，随后明确授权“开始开发，直到完成”；实施严格沿用已评审的阶段 0 边界 |
| 使用独立 `.planning` 目录 | 遵循 planning-with-files，保证长期迭代可恢复 |
| 用“稳定核心 + 可扩展 Runtime”替代“小核心” | small 描述职责和变化原因，不代表缩水或另做 Mini Pi |
| 在 ExtensionHost 之前增加阶段 0 | Pi 第 1、2 章暴露出当前双轨循环、Tool 安全和运行生命周期比插件发现更基础 |
| 阶段 0 只深挖现有生产循环，不引入 Mini Pi | 目标是复用行为并形成唯一 Interface，不创建平行框架 |
| Agent Loop、Tool Pipeline 和 AgentRun 分成三个深模块 | 三者的变化原因、测试面和生命周期不同，拆分后可让 TUI、Remote 与子 Agent 共享语义 |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| 初稿使用“Pi 式小核心”，可能被理解为 Mini Pi | 改为“以当前 MewCode 为主体，选择性参考 Pi 的 Runtime 与扩展机制” |
| 组合校验命令未启动：`Too many open files (os error 24)` | 已停止重复同一命令，改为拆分校验并继续记录结果 |
| 旧措辞校验误报规划日志中的历史错误记录 | 保留可追溯日志，把交付措辞校验范围修正为 `docs/` |
| Pi 两章的本地正文提取器返回少于 4 个非空行 | 公开 URL 按 read 技能降级到 `r.jina.ai`，正文成功获取；外部内容仅进入 `findings.md` |
