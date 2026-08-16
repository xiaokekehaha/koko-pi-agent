# Mini Pi Agent（Python 教学版）

这个案例只保留 Pi 最核心的循环：模型提出工具调用，Python 执行工具，把结果交回模型，直到模型给出最终回答。

## 运行

```bash
uv run python -m examples.mini_pi_agent.demo
uv run python -m pytest tests/test_mini_pi_agent.py -q
```

Demo 使用 `ScriptedLLMClient`，不访问网络，也不需要 API Key。

## 模块怎么理解

```text
Agent（有状态外壳）
  └── run_agent_loop（无状态发动机）
        ├── LLMClient（模型插座）
        ├── ToolRegistry（工具通讯录）
        └── Tool（真正干活的人）
              └── Pydantic（参数门卫）
```

- `models.py`：消息、工具调用、结果和事件这些“快递单”。
- `contracts.py`：规定模型和工具必须长什么样。
- `registry.py`：根据名字找到工具，同名注册直接失败。
- `loop.py`：运行 model -> tool -> model 循环。
- `agent.py`：保存消息历史，并阻止同一个 Agent 重入。
- `fake_llm.py`：给测试返回预先写好的模型响应。
- `tools.py`：两个确定性工具示例。
- `demo.py`：把所有部件装起来运行一次。

## 第一阶段刻意不做什么

不接真实模型，不做多 Agent、热重载、数据库会话、远程服务和权限界面。第一阶段先证明循环、参数验证、错误返回、权限阻断和终止条件正确。

## 高级能力分别是什么

### 多 Agent

多 Agent 不是“放很多模型在一起聊天”，而是把一个有明确输入输出的 Agent 当成另一个 Agent 的工具。

推荐技术：

- 同进程并发：`asyncio.TaskGroup`。
- 任务投递：`asyncio.Queue`。
- 隔离：每个子 Agent 独立 `AgentState`、工具集和 token 预算。
- 需要进程重启后恢复时：再评估 LangGraph 或 Temporal 一类持久化工作流。

最重要的边界是：子 Agent 不直接修改父 Agent 的消息列表，只返回结构化结果。

### 热重载

热重载是程序不退出，修改 Skill、配置或插件文件后重新加载它们。

推荐技术：

- `watchfiles.awatch()` 监听文件变化。
- `importlib` 加载 Python 模块。
- 每个插件必须提供 `start()` 和 `stop()`/`dispose()` 生命周期。
- 重新加载时创建新插件实例，不在旧实例上偷偷换类定义。

正确顺序是：停止旧消费者 -> 释放旧资源 -> 加载新实现 -> 重新满足依赖 -> 启动新消费者。只调用 `importlib.reload()` 而不清理旧任务、文件句柄和注册表，会产生“幽灵插件”。

### 数据库会话

数据库会话是把消息、工具调用、事件、分支和压缩摘要持久化，程序重启后还能继续。

推荐技术：

- 本地单用户：SQLite + `aiosqlite`。
- 多用户服务：PostgreSQL + `asyncpg`。
- 统一数据访问：SQLAlchemy 2 AsyncIO。
- 迁移：Alembic。

建议最少四张逻辑表：`sessions`、`entries`、`branches`、`checkpoints`。Entry 使用追加式写入和 `parent_id`，避免回退时覆盖历史。一个并发任务使用一个 `AsyncSession`，不要在多个 Agent 任务之间共享同一个数据库 Session。

### 远程服务

远程服务是让 Web、手机或其他进程通过网络使用 Agent。

推荐技术：

- FastAPI：创建/查询会话、发送 prompt、停止任务。
- WebSocket 或 SSE：传递流式文本和工具事件。
- Pydantic：请求、响应和事件协议。
- Uvicorn：运行 ASGI 服务。
- Redis：只有部署多个服务实例、需要共享任务状态时再引入。

网络层只传命令和事件，不应该复制一份 Agent Loop。CLI 和远程服务应该消费同一个内核。

### 复杂权限 UI

复杂权限 UI 不是一个弹窗，而是三层系统：

```text
策略层：allow / deny / ask
审批层：创建待审批请求，等待用户决定
展示层：Textual 弹窗或 Web 页面
```

推荐技术：

- 单用户 CLI：现有 Python 规则 + Textual `ModalScreen`。
- 多用户 RBAC/ABAC：Casbin。
- 远程审批：FastAPI + WebSocket，将审批结果送回等待中的 Future。
- 审计：追加式记录“谁、何时、批准了什么参数”。

真正的安全判断必须发生在 Tool 执行前的服务端。前端按钮只能展示和收集决定，不能成为唯一防线。

## 什么时候升级框架

| 需求 | 推荐选择 |
|---|---|
| 学习 Agent Loop、单机 Coding Agent | 当前轻量内核 |
| 长任务、检查点、人工暂停后恢复 | LangGraph |
| 多用户会话查询 | SQLAlchemy + PostgreSQL |
| 浏览器或移动端接入 | FastAPI + WebSocket/SSE |
| 插件文件运行中更新 | watchfiles + 可逆生命周期 |
| 多角色、多资源权限 | Casbin + 自定义审批层 |

框架应该在真实复杂度出现后再引入，不要为了“以后可能需要”提前把教学内核变成分布式系统。
