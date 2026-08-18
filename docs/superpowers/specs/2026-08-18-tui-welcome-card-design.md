# TUI 启动欢迎卡片设计

日期：2026-08-18
状态：已评审，待实现

## 背景

Koko 当前的 TUI 启动界面是 `app.py` 里的 `_make_banner()`：3 行 `RichText`，渲染成常驻
dock 在顶部的 `#title-bar`（`styles.tcss` 里固定 `height: 3`），内容是一个 3 行 ASCII 猫脸
加上 `Koko vX.Y.Z` / 模型名 / 工作目录。

两个问题：

1. 它永久占据 3 行垂直空间，而其中的信息（版本号、模型名）只在启动那一刻有价值。
2. 启动时不告诉用户任何"本次会话装配了什么"——加载了多少 skills、多少 sub-agents、
   MCP 连上没有、记忆恢复了没有。这些信息目前散落在系统消息里，或者根本不可见。

本设计把启动界面改造成一次性的开屏卡片：信息量做大，但只出现一次，随对话滚走。

## 目标与非目标

### 目标

- 启动时以一张卡片交付四类信息：身份（版本/模型/目录）、品牌（吉祥物）、
  上手提示（tips）、会话就绪状态（skills / agents / hooks / memory / MCP）。
- 顶部腾出 3 行常驻空间。
- 卡片在宽、中、窄三种终端宽度下都成立，不错位、不变形。
- 渲染逻辑可单测，不依赖 Textual 测试 harness。

### 非目标（明确不做）

| 不做 | 理由 |
|---|---|
| git 分支显示 | 引入 subprocess IO 与失败/超时分支，收益不抵成本 |
| 窗口 resize 时重排卡片 | 卡片是一次性的，滚走后重排无意义 |
| `-p` 模式的欢迎屏 | `-p` 是脚本用途，额外输出会污染 stdout |
| `--remote` 浏览器 UI 的欢迎屏 | 另一套渲染栈，独立课题 |
| 吉祥物动画 | `/mascot` 命令的 `MascotOverlay` 已经提供 |
| `What's new` / release notes 栏 | 需要长期维护 CHANGELOG，否则内容必然过期 |

## 设计决策

以下五项在评审中逐条确认：

1. **一次性开屏卡片**，不是常驻顶部 box。卡片 mount 进聊天区作为第一条内容，随对话滚走。
2. **右栏放 Tips + 本次会话就绪概览**，不做 `What's new`。就绪数据全部是现成的，零维护成本。
3. **吉祥物用彩色半块像素柯基**，与 `/mascot` 的 ASCII 动画版形成呼应而非重复。
4. **MCP 先渲染后原地回填**：卡片立即渲染，MCP 行先显示 `connecting…`，
   初始化完成后原地更新，需要认证或失败时在卡片下方追加警告行。
5. **三档响应式降级**：≥100 列双栏 / 70–99 列单栏堆叠 / <70 列三行精简。

## 架构

### 模块划分

```
koko_pi_agent/welcome.py        （新增，纯渲染，对 app.py 零依赖）
    WelcomeContext              dataclass，渲染的唯一输入
    MASCOT_WIDE / MASCOT_COMPACT / MASCOT_MINI
    TIPS                        tip 池
    render_welcome(ctx, width) -> RenderableType
    render_mcp_warning(ctx) -> RichText | None

koko_pi_agent/app.py            （修改）
    - 删除 _make_banner()
    - 删除 compose() 里的 #title-bar
    + _mount_welcome_card()     在 _select_provider_unlocked() 末尾调用
    + _refresh_welcome_mcp()    在 _init_mcp() 末尾调用
    + status-bar 增加 cwd 标签（补偿删除 title-bar 后 cwd 无处可查）

koko_pi_agent/styles.tcss       （修改）
    - 删除 #title-bar 规则
    + #welcome-card / #welcome-warning / #cwd-label 规则

tests/test_welcome.py           （新增）
```

`welcome.py` 是一个深模块：外部只需要知道"喂一个 `WelcomeContext` 和一个宽度，
拿回一个 Rich renderable"，内部的选档、布局、配色、tip 抽样都不外泄。
它不 import `app.py` 的任何东西，因此可以脱离 Textual 直接测试。

### 为什么是纯函数而不是 Textual 组件

考虑过用 `WelcomeCard(Vertical)` 容器 + TCSS 布局。放弃的理由：

- 卡片一次性，Textual 布局最大的优势（resize 自动重排）用不上。
- 双栏内的逐行对齐，Rich 的 `Table`/`Columns` 比 TCSS 精确。
- 像素艺术靠前景/背景双色成形，在 TCSS 下容易被 widget 自身背景覆盖。
- 测试需要起 Textual app harness，而纯函数只要一次调用。

也考虑过直接扩写 `_make_banner()`。放弃的理由：`app.py` 已经 2393 行，
这坨内容组装逻辑自成一体，不该再往里塞，且没有可测边界。

## 数据契约

```python
@dataclass
class WelcomeContext:
    app_name: str
    app_version: str
    user_name: str | None
    is_returning: bool
    model: str
    provider_name: str
    work_dir: str            # 已做 ~ 缩写
    skills_count: int
    agents_count: int
    hooks_count: int
    memory_entries: int
    mcp: McpState
    tips_seed: int | None = None   # 测试注入；None 表示随机
```

```python
@dataclass
class McpState:
    kind: Literal["none", "connecting", "ready", "warning"]
    server_count: int = 0
    tool_count: int = 0
    auth_needed: int = 0
    errors: tuple[str, ...] = ()
```

### 字段来源

全部在 `_select_provider_unlocked()` 里已经可用：

| 字段 | 来源 |
|---|---|
| `app_name` / `app_version` | `app.py` 的 `APP_NAME` / `APP_VERSION` |
| `user_name` | 依次尝试：`git config user.name` → `$USER` → `None`（`ProviderConfig` 与配置文件都没有 `user_name` 字段，不新增） |
| `is_returning` | `session_manager.list()` 里存在 `id` 不等于当前 session 的记录 |
| `model` / `provider_name` | `provider.model` / `provider.name` |
| `work_dir` | 已有的 `work_dir`，渲染前做 `~` 缩写 |
| `skills_count` | `len(skill_loader.get_catalog())` |
| `agents_count` | `len(agent_loader.list_agents())` |
| `hooks_count` | `len(hook_engine.hooks)` |
| `memory_entries` | `len(memory_manager.get_memories())` |
| `mcp` | 初始 `connecting`（`self._mcp_server_configs` 非空时）否则 `none` |

`user_name` 的 `git config user.name` 一路会 fork 一个 subprocess。为避免拖慢启动，
调用时设 1 秒超时，任何异常都静默降级到下一级。若最终为 `None`，
问候语退化为不带称呼的 `Welcome back!` / `Welcome to Koko!`。

`is_returning` 必须排除当前会话：`self.session = self.session_manager.create()`
发生在 `app.py:952`，远早于卡片挂载，所以 `list()` 必然包含刚创建的这一条。
直接判断 `list()` 非空会让 `is_returning` 恒为 `True`，首次使用的用户永远看不到
`Welcome to Koko`。正确写法是过滤掉 `id == self.session.session_id` 的那条再判空
（而不是简单地判断 `len(...) > 1`，因为不能假设 `create()` 一定已落盘可见）。

## 渲染规格

### 宽档（≥100 列）

双栏，约 12 行。左栏宽 34 列，右栏占剩余宽度。

```
╭─ Koko v0.3.1 ──────────────────────────────────────────────────────────────────────────╮
│                                                                                         │
│    Welcome back, xiaokezhou!      Tips for getting started                              │
│                                     Shift+Tab 切权限模式 · /plan 先规划再动手            │
│       ▄▀▀▄   ▄▀▀▄                   /worktree 让并发任务各自在独立工作树里改             │
│      █ ●  ▀▀▀  ● █                  /skill 看已加载技能 · /help 全部命令                 │
│      ▀█▄▄▄▄▄▄▄▄▄█▀                                                                      │
│        ▀█▀   ▀█▀                  Session ready                                         │
│                                     12 skills · 4 agents · 3 hooks · memory 8           │
│    claude-opus-5 · anthropic        MCP · connecting…                                   │
│    ~/workspace/koko                                                                     │
│                                                                                         │
╰─────────────────────────────────────────────────────────────────────────────────────────╯
 ⚠ 1 MCP server needs authentication · run /mcp
```

版本号 `Koko v0.3.1` 嵌在上边框（Rich `Panel` 的 `title`，左对齐）。

### 中档（70–99 列）

单栏堆叠，约 10 行。吉祥物转为横排紧凑版，身份信息移到吉祥物右侧，
Tips 与 Ready 各压成一行。

```
╭─ Koko v0.3.1 ──────────────────────────────────────────────────╮
│                                                                 │
│    ▄▀▀▄   ▄▀▀▄    Welcome back, xiaokezhou!                     │
│   █ ●  ▀▀▀  ● █   claude-opus-5 · anthropic                     │
│   ▀█▄▄▄▄▄▄▄▄▄█▀   ~/workspace/koko                              │
│     ▀█▀   ▀█▀                                                   │
│                                                                 │
│  Tips   Shift+Tab 切模式 · /plan 规划 · /skill 技能 · /help      │
│  Ready  12 skills · 4 agents · 3 hooks · MCP connecting…        │
│                                                                 │
╰─────────────────────────────────────────────────────────────────╯
```

中档只显示 2 条 tip（压进一行，超出则截断并以 `·` 收尾）。

### 窄档（<70 列）

无边框，3 行，吉祥物压成 3 行小图标。不显示 tips。

```
 ▄▀▄   Koko v0.3.1 · claude-opus-5
 █●●█  ~/workspace/koko
 ▀▀▀   12 skills · 4 agents · MCP connecting…
```

### 像素艺术实现

用 `▀`（上半块）配合前景色与背景色，一行文字表现两行像素：前景色画上半像素，
背景色画下半像素。柯基采用橘白双色，与主题紫 `#875FFF`（`_KOKO_THEME.primary`）
形成对比。数据以「每行一个 `(上半色号, 下半色号, 字符)` 序列」的形式常量化，
三档各一份，行数与上面的布局图一致：`MASCOT_WIDE` 4 行 / `MASCOT_COMPACT` 4 行
（同一张图，宽档竖排居中、中档横排靠左）/ `MASCOT_MINI` 3 行。

背景色使用终端默认（不显式设置），避免在浅色终端下出现黑色色块。

### Tips 池与抽样

`TIPS` 是一个字符串列表，每条形如 `"Shift+Tab 切权限模式 · /plan 先规划再动手"`。
渲染时用 `random.Random(ctx.tips_seed).sample(TIPS, k)` 抽样，宽档 `k=3`，中档 `k=2`，
窄档不抽。`tips_seed` 为 `None` 时用系统随机源，测试注入固定整数保证可断言。

初始 tip 池覆盖：权限模式切换、plan 模式、worktree 隔离、skills、后台任务、
memory 与上下文压缩、工具块折叠、rewind。

**约束**：tip 里出现的每个斜杠命令都必须是已注册命令。当前已注册的是
`/help` `/compact` `/clear` `/plan` `/session` `/mcp` `/memory` `/mascot`
`/permission` `/sandbox` `/rewind` `/status` `/skill`（`ALL_COMMANDS`）加上
`/worktree` `/tasks` `/trace`（在 `_select_provider_unlocked` 里动态注册）。
注意 `commands/handlers/review.py` 定义了 `REVIEW_COMMAND` 但从未注册，
`/review` 不可用；也不存在 `/team` 命令——多智能体团队没有斜杠命令入口。

## 生命周期与 MCP 回填

### 挂载

`_select_provider_unlocked()` 末尾（当前调用 `_make_banner` 更新 title-bar 的位置，
`app.py:1153` 附近）改为调用 `_mount_welcome_card()`：

1. 组装 `WelcomeContext`。
2. `width = self.query_one("#chat-area").size.width`，取一次，不监听后续变化。
3. `card = Static(render_welcome(ctx, width), id="welcome-card")`。
4. `await self.query_one("#chat-area", VerticalScroll).mount(card)`。
5. 把 `ctx`、`card` 与结算后的宽度存到 `self._welcome_ctx` / `self._welcome_card` /
   `self._welcome_width`，供 MCP 回填时以同一宽度重渲染。

`#chat-area` 在 provider 选择阶段 `display = False`，此时 `size.width` 为 0。
挂载发生在同一函数里 `display = True` 之后，但 Textual 的尺寸可能尚未结算，
因此 `_mount_welcome_card()` 需要在 mount 后于下一帧（`call_after_refresh`）
读取实际宽度并做一次重渲染；若读到的宽度为 0，退回到 `self.size.width`。

### MCP 回填

`_init_mcp()`（`app.py:2201`）末尾已经算出 `server_count`、`mcp_tools`、
`connect_result.errors`。在现有的 `_show_system_message(f"MCP warning: {err}")`
循环之后，新增一次 `_refresh_welcome_mcp(server_count, mcp_tools, connect_result.errors)`：

1. 用新的 `McpState` 替换 `self._welcome_ctx.mcp`。
2. `self._welcome_card.update(render_welcome(ctx, self._welcome_width))` ——
   以挂载时结算的同一宽度原地重渲染整张卡片，避免回填导致布局跳档。
3. 若 `render_mcp_warning(ctx)` 返回非 `None`，mount 一个
   `Static(..., id="welcome-warning")` 到卡片下方；若已存在则更新。

若用户在 MCP 初始化完成前已经发过消息，卡片可能已经滚出视野。原地更新仍然正确
（内容变了，只是用户未必看到），警告行则 mount 在卡片正下方而非对话末尾，
保持与卡片的视觉关联。MCP 失败的即时可见性由既有的 `_show_system_message` 路径承担，
本设计不改变它。

`self._welcome_card` 为 `None`（卡片未挂载或已被 `/clear` 清掉）时，回填静默跳过。

### `/clear` 的交互

`/clear` 清空聊天区会一并移除卡片。这是预期行为——卡片属于对话流的一部分。
清空后 `self._welcome_card` 需置为 `None`，避免 MCP 回填操作已卸载的 widget。

## 顶部空间与 cwd 补偿

删除 `#title-bar` 后，工作目录不再有任何常驻展示位。在 `#status-bar`
（已含 `#mode-label` / `#teammates-label` / `#model-label`）新增 `#cwd-label`，
显示 `~` 缩写后的工作目录，窄终端下由 TCSS 的 `text-overflow` 截断。

## 错误处理

`render_welcome()` 不抛异常：所有计数字段为 0 时正常渲染（显示 `no skills` 一类的
空态文案而非 `0 skills`），`user_name` 为 `None` 时退化为无称呼问候，
`work_dir` 为空字符串时该行省略。

`_mount_welcome_card()` 整体包在 `try/except` 里，任何失败都降级为不挂载卡片并
记录一条系统消息——启动流程不能因为一个装饰性组件而中断。

## 测试策略

`tests/test_welcome.py`，全部是对纯函数的同步调用，不需要 Textual harness：

- **三档选档**：宽度 120 / 85 / 50 各渲染一次，断言输出行数落在预期区间，
  且宽档含双栏分隔特征、窄档不含边框字符。
- **MCP 四态**：`none` / `connecting` / `ready` / `warning` 各断言对应文案出现，
  且 `render_mcp_warning()` 只在 `warning` 态返回非 `None`。
- **问候语**：`is_returning=True` 出现 `Welcome back`，`False` 出现 `Welcome to Koko`；
  `user_name=None` 时不出现多余的逗号或空称呼。
- **tips 可复现**：同一 `tips_seed` 两次渲染输出一致；宽档 3 条、中档 2 条、
  窄档 0 条。
- **空态**：所有计数为 0、`mcp.kind="none"`、`user_name=None`、`work_dir=""`
  时不抛异常。
- **宽度边界**：99 / 100 与 69 / 70 四个值各渲染一次，确认选档边界符合规格。

`app.py` 侧的挂载与回填不写新测试——它们是薄适配层，且现有测试套件不覆盖 TUI 挂载。

## 实现顺序

1. `welcome.py`：`WelcomeContext` / `McpState` / 三档像素常量 / `TIPS`。
2. `tests/test_welcome.py`：按上述策略写测试（此时全红）。
3. `render_welcome()` / `render_mcp_warning()`：实现到测试全绿。
4. `app.py`：删 `_make_banner` 与 `#title-bar`，加 `_mount_welcome_card()` 与
   `_refresh_welcome_mcp()`，status-bar 加 `#cwd-label`。
5. `styles.tcss`：删旧规则，加新规则。
6. 手工验证：`uv run koko` 在 120 / 85 / 50 三种终端宽度下各启动一次，
   分别在有 MCP 配置与无 MCP 配置下确认回填与警告行。
