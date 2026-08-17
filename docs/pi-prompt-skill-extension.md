# Pi 的三条扩展轴：Prompt Template、Skill、Extension

> - 源码基准：`github.com/earendil-works/pi` main 分支，2026-08-17
> - 姊妹篇：[Pi 五层架构逐层详解](./pi-layered-architecture.md)
> - 关注点：三者的区别、实现、加载时机、加载方式、释放方式，附一个 Skill 的完整生命周期案例

## 1. 一句话区分

三者看起来都是"往 agent 里加东西"，但它们**加在完全不同的位置**：

| | Prompt Template | Skill | Extension |
| --- | --- | --- | --- |
| 本质 | 用户输入的**宏展开** | 给模型的**按需说明书** | 改变 agent 行为的**代码** |
| 形态 | `.md`（frontmatter + 正文） | 目录 + `SKILL.md` + 附属脚本/资源 | `.ts` / `.js` 模块，default export 一个函数 |
| 谁消费 | **用户**（在编辑器里打 `/name`） | **模型**（自己决定要不要读） | **运行时**（挂进内核的回调槽） |
| 何时进上下文 | 展开的瞬间，作为 user 消息 | 描述常驻系统提示；正文按需读入 | 不进上下文，进的是执行路径 |
| 能否改行为 | 不能，只是文本 | 不能，只是文本（但能指挥模型跑脚本） | **能**：拦截工具、注册工具、注册命令、改上下文、改 header |
| 有无状态 | 无 | 无 | **有**：闭包变量、后台任务、连接 |
| 释放成本 | 零 | 零 | **需要显式失效** |

一条经验法则：

> **要改文字，用 Prompt Template。要教模型一套流程，用 Skill。要改代码路径，才用 Extension。**

按这个顺序从上往下选，越往下代价越大——Extension 能做前两者的一切，但它带来模块缓存、注册项所有权、句柄失效这些真实成本。

---

## 2. Prompt Template：用户侧的宏

### 实现

`src/core/prompt-templates.ts`，285 行，全部是纯函数。

```typescript
export interface PromptTemplate {
  name: string;          // 文件名去掉 .md
  description: string;   // frontmatter，缺省时取正文第一行非空行
  content: string;       // 正文
  // argument-hint、sourceInfo 等
}
```

展开逻辑就是一次字符串替换（`:269-284`）：

```typescript
export function expandPromptTemplate(text: string, templates: PromptTemplate[]): string {
  if (!text.startsWith("/")) return text;
  const match = text.match(/^\/([^\s]+)(?:\s+([\s\S]*))?$/);
  if (!match) return text;
  const template = templates.find((t) => t.name === match[1]);
  if (template) {
    const args = parseCommandArgs(match[2] ?? "");
    return substituteArgs(template.content, args);   // $1 $2 $@ ${1:-default} ${@:N:L}
  }
  return text;                                        // 不认识就原样透传
}
```

参数语法直接借了 shell 的形状：`$1`、`$@`、`$ARGUMENTS`、`${1:-default}`、`${@:N}`、`${@:N:L}`。

### 加载

| 何时 | 启动时 + `/reload` 时，随 `ResourceLoader.reload()` 一起 |
| --- | --- |
| 从哪 | `~/.pi/agent/prompts/*.md`、`.pi/prompts/*.md`（需项目信任）、包的 `prompts/`、settings 的 `prompts` 数组、CLI `--prompt-template` |
| 怎么加载 | 读文件 → 解析 frontmatter → 存成 `PromptTemplate[]`。**正文全量读进内存**——模板通常只有几十行 |
| 特别之处 | **非递归**。`prompts/` 下的子目录不会被扫描，要用就得在 settings 或包清单里显式列出 |

### 释放

不需要。`PromptTemplate[]` 是不可变数据，`reload()` 时整个数组被新数组替换，旧的交给 GC。**没有句柄、没有副作用、没有清理顺序问题。**

---

## 3. Skill：模型侧的渐进式披露

### 核心设计：只加载元数据

这是 Skill 最重要的一点。看 `src/core/skills.ts:74-81` 的数据结构：

```typescript
export interface Skill {
  name: string;
  description: string;
  filePath: string;        // ← 只存路径
  baseDir: string;         // ← skill 目录，相对路径的解析基准
  sourceInfo: SourceInfo;
  disableModelInvocation: boolean;
}
```

**没有 `content` 字段。** 启动时只解析 frontmatter，正文一个字节都不读。

注入系统提示时也只有三样东西（`:335-361`）：

```typescript
export function formatSkillsForPrompt(skills: Skill[]): string {
  const visibleSkills = skills.filter((s) => !s.disableModelInvocation);
  if (visibleSkills.length === 0) return "";
  const lines = [
    "\n\nThe following skills provide specialized instructions for specific tasks.",
    "Use the read tool to load a skill's file when the task matches its description.",
    "When a skill file references a relative path, resolve it against the skill directory ...",
    "", "<available_skills>",
  ];
  for (const skill of visibleSkills) {
    lines.push("  <skill>");
    lines.push(`    <name>${escapeXml(skill.name)}</name>`);
    lines.push(`    <description>${escapeXml(skill.description)}</description>`);
    lines.push(`    <location>${escapeXml(skill.filePath)}</location>`);
    lines.push("  </skill>");
  }
  lines.push("</available_skills>");
  return lines.join("\n");
}
```

**加载机制就是让模型自己调 `read` 工具去读那个 `location`。** 没有专门的 skill 加载器、没有 skill 工具、没有 RAG——复用已有的文件读取工具。

由此推出一个漂亮的一致性检查（`src/core/system-prompt.ts:65`、`:155`）：

```typescript
if (hasRead && skills.length > 0) {
  prompt += formatSkillsForPrompt(skills);
}
```

**`read` 工具不可用时，skill 清单根本不注入。** 因为清单里那句"use the read tool to load"会指向一个不存在的工具，注入了只会浪费 token 并制造幻觉。

### 加载时机与发现规则

| 何时 | 启动时扫描；`/reload` 时重扫；扩展的 `resources_discover` 事件可追加路径 |
| --- | --- |
| 从哪 | `~/.pi/agent/skills/`、`~/.agents/skills/`、`.pi/skills/`、`cwd` 及祖先目录的 `.agents/skills/`（到 git 根为止）、包的 `skills/`、settings 的 `skills` 数组、CLI `--skill` |

发现规则在 `loadSkillsFromDirInternal()`（`:173-275`），有三条容易踩的细则：

**1. 遇到 `SKILL.md` 就停止下潜。** 第一轮循环专门找 `SKILL.md`，找到就 `return`（`:194-221`）——一个 skill 目录内部的子目录不会被当成别的 skill。这就是为什么 `references/`、`scripts/` 可以放在 skill 目录里而不会被误认。

**2. 根级 `.md` 的待遇因目录而异。** `includeRootFiles` 参数控制：只有 `~/.pi/agent/skills/` 和 `.pi/skills/` 的**直接子文件** `.md` 会被当成 skill；递归进子目录后该标志变成 `false`（`:256`），`~/.agents/skills/` 的根级 `.md` 被忽略。

**3. 尊重 ignore 文件。** `.gitignore`、`.ignore`、`.fdignore` 都会被读取并按相对路径加前缀（`:47-65`），所以 skill 目录里被 git 忽略的东西不会被扫。`node_modules` 硬编码跳过。

去重与冲突（`:399-428`）：

```typescript
const realPath = canonicalizePath(skill.filePath);
if (realPathSet.has(realPath)) continue;              // 同一个文件经由 symlink 被扫到两次 → 静默跳过
const existing = skillMap.get(skill.name);
if (existing) {
  collisionDiagnostics.push({ type: "collision", ... }); // 同名不同文件 → 警告
} else {
  skillMap.set(skill.name, skill);
}
```

**同名先到先得，后来者只产生一条 collision 诊断。** 加载顺序决定谁赢：`includeDefaults` 时先 user 后 project，之后才是显式 `skillPaths`。

校验（`:92-127`、`:289-307`）是"宽进严出"的反面——**只有 description 缺失才拒绝加载**，name 超长、含大写、连续连字符都只是 warning，skill 照常可用。理由写在文档里：Pi 故意不要求 name 与父目录同名，因为那条标准规则对「多个 harness 共享的 skill 目录」不友好。

### 两条触发路径

**路径 A：模型自主判断。** 描述在系统提示里，模型觉得匹配就调 `read`。文档坦率承认这条路不可靠：*"models don't always do this; use prompting or `/skill:name` to force it"*。

**路径 B：用户显式调用 `/skill:name args`。** 实现在 `agent-session.ts:1309-1333`：

```typescript
private _expandSkillCommand(text: string): string {
  if (!text.startsWith("/skill:")) return text;
  const spaceIndex = text.indexOf(" ");
  const skillName = spaceIndex === -1 ? text.slice(7) : text.slice(7, spaceIndex);
  const args      = spaceIndex === -1 ? ""            : text.slice(spaceIndex + 1).trim();

  const skill = this.resourceLoader.getSkills().skills.find((s) => s.name === skillName);
  if (!skill) return text;                             // 不认识就原样透传

  const content = readFileSync(skill.filePath, "utf-8");
  const body = stripFrontmatter(content).trim();
  const skillBlock = `<skill name="${skill.name}" location="${skill.filePath}">\n`
                   + `References are relative to ${skill.baseDir}.\n\n${body}\n</skill>`;
  return args ? `${skillBlock}\n\n${args}` : skillBlock;
}
```

注意 `References are relative to ${skill.baseDir}` 这一行——**它是用户路径独有的**。模型路径下这条信息由系统提示里那句通用说明承担（"resolve it against the skill directory"）。两条路径都必须解决同一个问题：SKILL.md 里写的 `./scripts/process.sh` 到底相对于谁。

展开结果会被 `parseSkillBlock()`（`agent-session.ts:129-138`）反向解析，用于 UI 渲染时把 skill 块折叠起来而不是把几百行正文糊在屏幕上。

`disable-model-invocation: true` 的 skill 从系统提示里被过滤掉（`skills.ts:336`），**只能走路径 B**——适合那些"用户明确要求时才该跑"的危险操作。

### 释放

和 Prompt Template 一样：**不需要**。`Skill[]` 是不可变元数据，`reload()` 时整体替换。

正文的"释放"更彻底——它压根没被持有过。模型读进来的内容存在于对话历史里，跟着**压缩**走：上下文压缩时，一次早就用完的 skill 正文会被摘要掉。这是渐进式披露的另一半好处：**加载是懒的，卸载是自动的。**

---

## 4. Extension：代码，需要真的释放

### 实现：一个空容器 + 一个工厂函数

`src/core/extensions/loader.ts:469-516`：

```typescript
function createExtension(extensionPath: string, resolvedPath: string): Extension {
  return {
    path: extensionPath,
    resolvedPath,
    sourceInfo: createSyntheticSourceInfo(...),
    handlers:         new Map(),   // ← pi.on() 往这里塞
    tools:            new Map(),   // ← pi.registerTool() 往这里塞
    messageRenderers: new Map(),
    entryRenderers:   new Map(),
    commands:         new Map(),   // ← pi.registerCommand() 往这里塞
    flags:            new Map(),
    shortcuts:        new Map(),
  };
}

async function loadExtension(extensionPath, cwd, eventBus, runtime, cacheToken) {
  const factory = await loadExtensionModule(resolvedPath, cacheToken);   // ① 动态 import
  if (typeof factory !== "function") return { extension: null, error: "..." };
  const extension = createExtension(extensionPath, resolvedPath);        // ② 建空容器
  const api = createExtensionAPI(extension, runtime, cwd, eventBus);     // ③ API 绑定到这个容器
  await factory(api);                                                    // ④ 跑扩展代码，往容器里塞
  return { extension, error: null };
}
```

**这四步里藏着整个所有权模型：注册表不是全局的，而是每个扩展自己的七个 Map。** 全局只持有一个 `Extension[]`。

这个选择的直接后果是：**卸载一个扩展 = 从数组里去掉它的对象。** 不需要遍历全局注册表找出"哪些工具是这个扩展注册的"，因为那些工具从来就在它自己身上。

对比常见的反模式——全局 `toolRegistry.register(name, fn)`——那种设计下注册表知道有这个工具，但不知道它来自谁，卸载时要么留垃圾，要么得额外维护一张来源表。

### 加载

```typescript
const jiti = createJiti(import.meta.url, {
  moduleCache: false,                    // ← 关键：不用 Node 的模块缓存
  ...(isBunBinary ? { virtualModules: VIRTUAL_MODULES, tryNative: false }
    : isTypeScriptSourceRuntime ? { virtualModules: VIRTUAL_MODULES, tsconfigPaths: true }
    : { alias: getAliases() }),
});
const module = await jiti.import(extensionPath, { default: true });
```

用 [jiti](https://github.com/unjs/jiti) 而不是原生 `import()`，是为了**直接运行 TypeScript 而不需要用户编译**。`moduleCache: false` 是热重载能工作的前提——Node 的 ESM 缓存一旦缓存了模块就无法失效，`/reload` 会拿到旧代码。

pi 自己在上面加了一层可控缓存（`:146-167`、`:428-463`）：

```typescript
let extensionCacheCwd: string | undefined;
let extensionCacheGeneration = 0;
const extensionCache = new Map<string, ExtensionFactory>();

export function clearExtensionCache(): void {
  extensionCache.clear();
  extensionCacheCwd = undefined;
  extensionCacheGeneration++;     // ← 代际递增，旧 token 自动失效
}
```

缓存键带 `cwd` 和 `generation`。cwd 一变（切项目）自动清空；`generation` 递增让所有旧的 `cacheToken` 立刻失效，不用逐个通知持有者。**用单调递增的代际号做批量失效，比维护订阅者列表简单得多。**

加载时机：

| 阶段 | 加载什么 |
| --- | --- |
| 启动第一趟 | `loadProjectTrustExtensions()`——**强制把项目设为不信任**，只加载 user/global 和 CLI `-e` 扩展 |
| 信任决议 | 这批扩展参与 `project_trust` 事件，可以决定要不要信任当前项目 |
| 启动第二趟 | 信任确定后 `reload()`，这次才带上 `.pi/extensions/` |
| `/reload` | 完整走一遍下面的释放流程 |

这个两趟设计是安全边界：**项目级扩展在项目被信任之前一行都不会执行**，而信任决策本身可以被全局扩展接管。

### 释放：显式失效 + 整体重建

`agent-session.ts:2610-2635`：

```typescript
async reload(options?: { beforeSessionStart?: () => void | Promise<void> }): Promise<void> {
  const oldRunner = this._extensionRunner;
  const previousFlagValues = oldRunner.getFlagValues();                          // ① 保留用户设的 flag
  await emitSessionShutdownEvent(oldRunner, { type: "session_shutdown", reason: "reload" });  // ② 给扩展清理机会
  oldRunner.invalidate();                                                        // ③ 毒化旧句柄
  await this.settingsManager.reload();
  this.syncQueueModesFromSettings();
  resetApiProviders();
  await this._resourceLoader.reload();                                           // ④ clearExtensionCache + 重扫三类资源
  this._buildRuntime({ ..., flagValues: previousFlagValues });                   // ⑤ 造全新的 ExtensionRunner
  if (hasBindings) {
    await options?.beforeSessionStart?.();
    await this._extensionRunner.emit({ type: "session_start", reason: "reload" });  // ⑥ 新扩展开张
    await this.extendResourcesFromExtensions("reload");
  }
}
```

第 ③ 步 `invalidate()` 值得单独说。它不做任何清理，只设一个字符串（`runner.ts:544-556`）：

```typescript
message = "This extension ctx is stale after session replacement or reload. Do not use a captured pi "
        + "or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload(). "
        + "For newSession, fork, and switchSession, move post-replacement work into withSession and use "
        + "the ctx passed to withSession. For reload, do not use the old ctx after await ctx.reload().";

private assertActive(): void {
  if (this.staleMessage) throw new Error(this.staleMessage);
}
```

然后 `ExtensionRunner` 上**十几个方法**在入口调 `assertActive()`。

这是一个很值得学的设计：**扩展代码里捕获的 `ctx` 是无法回收的**——它可能存在某个闭包、某个 `setInterval` 回调、某个未完成的 promise 里。与其假装能追回来，不如**把旧句柄毒化**：谁敢用，立刻抛错，而且错误信息直接告诉他正确的写法是什么（用 `withSession` 拿新 ctx）。

**失败得早、失败得清楚，好过悄悄操作一个已经死掉的会话。**

真正的资源清理（定时器、文件监听、子进程、网络连接）靠 `session_shutdown` 事件，由扩展自己负责——pi 不做自动追踪。`session_shutdown` 在 `/reload`、`/new`、`/resume`、`/fork` 和进程退出（Ctrl+C、SIGTERM）时都会发。

### 释放语义对照

| | 谁负责 | 机制 |
| --- | --- | --- |
| 注册项（工具/命令/事件/渲染器） | 运行时 | 扔掉 `Extension` 对象即可，注册项在它身上 |
| 模块代码 | 运行时 | `clearExtensionCache()` + jiti `moduleCache: false` |
| 旧 ctx 句柄 | 运行时 | `invalidate()` 毒化，`assertActive()` 抛错 |
| 定时器/监听器/连接/子进程 | **扩展自己** | 订阅 `session_shutdown` 事件 |

最后一行是 pi 的取舍：**不做自动资源追踪。** 这和 README 里"pi 不内置权限系统，需要边界就上容器"是同一种立场——把机制给足，策略留给上层。代价是一个写得不好的扩展可以泄漏 handle；收益是内核不用维护一套资源生命周期框架。

---

## 5. 案例：一个 Skill 从磁盘走到模型手里

假设有这么个 skill：

```
~/.pi/agent/skills/pdf-tools/
├── SKILL.md
├── scripts/
│   ├── extract.py
│   └── merge.py
└── references/
    └── pypdf-api.md          # 800 行 API 参考
```

`SKILL.md`：

```markdown
---
name: pdf-tools
description: Extracts text and tables from PDF files, fills PDF forms, and merges
  multiple PDFs. Use when working with PDF documents.
---

# PDF Tools

## Setup
uv pip install pypdf pdfplumber

## Extract text
./scripts/extract.py <input.pdf> [--pages 1-5]

## Merge
./scripts/merge.py out.pdf in1.pdf in2.pdf

详细 API 见 [references/pypdf-api.md](references/pypdf-api.md)。
```

### 阶段 1 · 启动扫描（几毫秒，不读正文）

`loadSkills()` 扫到 `~/.pi/agent/skills/`，进入 `pdf-tools/` 目录，第一轮循环命中 `SKILL.md` → **立即 return，不再递归**（`skills.ts:194-221`）。所以 `scripts/` 和 `references/` 不会被当成别的 skill。

`loadSkillFromFile()` 读文件、`parseFrontmatter()` 拿到 name 和 description，然后**丢掉正文**，只留：

```typescript
{
  name: "pdf-tools",
  description: "Extracts text and tables from PDF files, ...",
  filePath: "/Users/me/.pi/agent/skills/pdf-tools/SKILL.md",
  baseDir:  "/Users/me/.pi/agent/skills/pdf-tools",
  disableModelInvocation: false,
}
```

### 阶段 2 · 注入系统提示（约 60 token）

```xml
<available_skills>
  <skill>
    <name>pdf-tools</name>
    <description>Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents.</description>
    <location>/Users/me/.pi/agent/skills/pdf-tools/SKILL.md</location>
  </skill>
</available_skills>
```

**成本对比**：这段约 60 token。SKILL.md 正文约 200 token，`references/pypdf-api.md` 约 12000 token。如果全量注入，20 个 skill 就能吃掉十几万 token；渐进式披露下，20 个 skill 的常驻成本约 1200 token。

### 阶段 3A · 模型自主加载

```
用户：帮我把这三个 PDF 合成一个
  ↓
模型看到 <available_skills> 里 description 提到 "merges multiple PDFs"
  ↓
发出 toolCall: read { file_path: "/Users/me/.pi/agent/skills/pdf-tools/SKILL.md" }
  ↓
agent-loop.ts:600-668  prepare：找到 read 工具 → 校验参数 → beforeToolCall（扩展可拦截）
agent-loop.ts:670-711  execute：读文件
agent-loop.ts:713-758  finalize：afterToolCall
  ↓
ToolResultMessage 进 context，模型拿到 SKILL.md 全文（+200 token）
  ↓
模型按说明书发出 toolCall: bash { command: "/Users/me/.pi/agent/skills/pdf-tools/scripts/merge.py out.pdf a.pdf b.pdf c.pdf" }
```

注意最后一步的路径。SKILL.md 里写的是相对路径 `./scripts/merge.py`，模型能拼出绝对路径，靠的是系统提示里那句：

> *"When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands."*

而 `<location>` 给了它 SKILL.md 的绝对路径。**`location` 不只是"去哪读"，也是"相对路径以谁为基准"。**

如果模型需要更细的 API 细节，它会再读 `references/pypdf-api.md`——**第三层披露**。绝大多数任务停在第二层。

### 阶段 3B · 用户显式调用

```
用户输入：/skill:pdf-tools 合并当前目录下所有 PDF
```

`AgentSession.prompt()` 的处理顺序（`:1116-1164`）很关键：

```typescript
// ① 扩展命令优先，命中就完全绕过 agent loop
if (expandPromptTemplates && text.startsWith("/")) {
  const handled = await this._tryExecuteExtensionCommand(text);
  if (handled) return;
}

// ② 扩展的 input 事件，可拦截/转换/直接处理
if (this._extensionRunner.hasHandlers("input")) {
  const inputResult = await this._extensionRunner.emitInput(...);
  if (inputResult.action === "handled")   return;
  if (inputResult.action === "transform") currentText = inputResult.text;
}

// ③ 先展开 skill，再展开 prompt template
let expandedText = currentText;
expandedText = this._expandSkillCommand(expandedText);
expandedText = expandPromptTemplate(expandedText, [...this.promptTemplates]);
```

**这个顺序定义了三条轴的优先级**：Extension 命令 > Extension input 拦截 > Skill 展开 > Prompt Template 展开。越靠前的越有能力短路后面的。

展开结果是一条 user 消息：

```
<skill name="pdf-tools" location="/Users/me/.pi/agent/skills/pdf-tools/SKILL.md">
References are relative to /Users/me/.pi/agent/skills/pdf-tools.

# PDF Tools

## Setup
uv pip install pypdf pdfplumber
...
</skill>

合并当前目录下所有 PDF
```

和路径 A 的区别：

| | 路径 A（模型自主） | 路径 B（`/skill:`） |
| --- | --- | --- |
| 正文如何进上下文 | 一次 `read` 工具调用的**结果消息** | 直接是 **user 消息的一部分** |
| 花几轮 | 至少两轮（读 + 干活） | 一轮 |
| 可靠性 | 模型可能不读 | **一定加载** |
| baseDir 提示 | 靠系统提示的通用说明 | 显式写进 skill 块 |
| 能否被 `beforeToolCall` 拦截 | 能（是个 read 调用） | 不能（没有工具调用） |

### 阶段 4 · 释放

**skill 正文**：没有任何组件持有它。它作为消息躺在会话历史里，跟着上下文压缩走——`_checkCompaction()` 触发时，一段早已用完的 skill 正文会被摘要成一句话。**加载是懒的，卸载是自动的。**

**skill 元数据**：`/reload` 时 `ResourceLoader.reload()` 重扫目录，`Skill[]` 整体替换。改了 SKILL.md 的 description，`/reload` 之后系统提示里就是新的。

**唯一需要留神的**：正在进行的会话里，模型可能已经读过旧版 SKILL.md。`/reload` 换掉的是元数据和未来的系统提示，**换不掉历史消息里那份旧正文**。

---

## 6. 三者如何互相作用

**Extension 可以贡献 Skill 和 Prompt 的路径。** `resources_discover` 事件（`agent-session.ts:2262-2285`）：

```typescript
private async extendResourcesFromExtensions(reason: "startup" | "reload"): Promise<void> {
  if (!this._extensionRunner.hasHandlers("resources_discover")) return;
  const { skillPaths, promptPaths, themePaths } =
    await this._extensionRunner.emitResourcesDiscover(this._cwd, reason);
  if (skillPaths.length === 0 && promptPaths.length === 0 && themePaths.length === 0) return;
  this._resourceLoader.extendResources({ skillPaths: ..., promptPaths: ..., themePaths: ... });
  this._baseSystemPrompt = this._rebuildSystemPrompt(this.getActiveToolNames());  // ← 重建系统提示
  this.agent.state.systemPrompt = this._baseSystemPrompt;
}
```

一个扩展可以在启动时去远端拉一批 skill、解压到临时目录，然后把路径交回来。追加进来的资源标 `scope: "temporary"`。

注意最后两行：**追加 skill 之后立刻重建系统提示并写回 `agent.state.systemPrompt`**。而每一轮的 `prepareNextTurnWithContext`（`:535-556`）又会把 `_baseSystemPrompt` 重新灌进 context——所以这个改动**在下一轮 LLM 调用就生效**，不需要重启会话。

**加载的完整时序**：

```
进程启动
  ├─ ResourceLoader 构造
  ├─ loadProjectTrustExtensions()      ← 只加载 user/global + CLI 扩展
  ├─ project_trust 事件                 ← 这批扩展可以决定信任与否
  ├─ ResourceLoader.reload()            ← 信任确定，加载全部三类资源
  │    ├─ clearExtensionCache()
  │    ├─ 扫 extensions → jiti import → factory(api) → Extension 对象
  │    ├─ 扫 skills     → 只读 frontmatter
  │    ├─ 扫 prompts    → 读全文
  │    └─ 扫 themes / AGENTS.md / system prompt 覆盖
  ├─ 构建系统提示（skills 的 XML 在这里拼进去，前提是 read 工具可用）
  ├─ session_start 事件
  └─ resources_discover 事件            ← 扩展追加路径 → 重建系统提示

/reload
  ├─ session_shutdown 事件（扩展清理自己的资源）
  ├─ oldRunner.invalidate()             ← 毒化旧 ctx
  └─ 重跑上面整条链路
```

---

## 7. 对 MewCode 的启发

| 做法 | 值不值得抄 |
| --- | --- |
| **Skill 只加载元数据，正文交给 read 工具** | 值。省 token，且零额外机制——不需要 skill 加载器、不需要 RAG |
| **`read` 工具不可用就不注入 skill 清单** | 值。一行 `if`，防止系统提示自相矛盾 |
| **注册项挂在扩展对象自己身上，不进全局注册表** | 非常值。这直接解决设计文档里"注册表知道对象，不知道来自哪个扩展"那条 |
| **旧 ctx 毒化 + 明确错误信息**，而不是假装能回收 | 非常值。Python 侧对应的是：`ExtensionSession` 关闭后所有 API 抛 `RuntimeError`，消息里写清正确用法 |
| **代际号（generation）做批量缓存失效** | 值。比维护订阅者列表简单 |
| **项目信任前只加载全局扩展，且信任决策可被扩展接管** | 值，尤其是团队共享 `.koko/` 配置的场景 |
| 资源清理（定时器/连接）完全交给扩展自己 | **不建议照抄**。Python 有 `AsyncExitStack` 和 `TaskGroup`，做自动清理的成本远低于 TS。设计文档里的 `ResourceScope` + `TaskSupervisor` 方向比 pi 更稳 |

最后一条是这次对照里唯一「MewCode 应该比 pi 做得更多」的地方。pi 选择不做资源追踪是 TypeScript 生态的现实约束；Python 的 `async with` + `AsyncExitStack` 能用几十行拿到确定性的逆序清理，没有理由放弃。

---

## 8. 源码索引

**Prompt Template**
- `src/core/prompt-templates.ts:11-22` — PromptTemplate 结构
- `src/core/prompt-templates.ts:24-68` — parseCommandArgs
- `src/core/prompt-templates.ts:70-175` — substituteArgs（`$1` / `$@` / `${1:-default}` / `${@:N:L}`）
- `src/core/prompt-templates.ts:269-284` — expandPromptTemplate
- `docs/prompt-templates.md` — 用户文档

**Skill**
- `src/core/skills.ts:74-81` — Skill 结构（**无 content 字段**）
- `src/core/skills.ts:92-127` — name / description 校验
- `src/core/skills.ts:168-275` — 目录发现规则
- `src/core/skills.ts:277-325` — loadSkillFromFile（只解析 frontmatter）
- `src/core/skills.ts:335-361` — formatSkillsForPrompt（XML 注入）
- `src/core/skills.ts:387-487` — loadSkills（去重、冲突、来源）
- `src/core/system-prompt.ts:63-66, 154-157` — `hasRead` 守卫
- `src/core/agent-session.ts:129-138` — parseSkillBlock
- `src/core/agent-session.ts:1309-1333` — _expandSkillCommand
- `docs/skills.md` — 用户文档

**Extension**
- `src/core/extensions/loader.ts:146-167` — 缓存与代际号
- `src/core/extensions/loader.ts:436-464` — jiti 动态加载
- `src/core/extensions/loader.ts:469-488` — createExtension（七个 Map）
- `src/core/extensions/loader.ts:490-516` — loadExtension 四步
- `src/core/extensions/runner.ts:189-201` — emitSessionShutdownEvent
- `src/core/extensions/runner.ts:544-556` — invalidate / assertActive
- `src/core/resource-loader.ts:379-385` — loadProjectTrustExtensions
- `src/core/resource-loader.ts:387-546` — reload 全流程
- `src/core/agent-session.ts:2262-2285` — extendResourcesFromExtensions
- `src/core/agent-session.ts:2610-2635` — AgentSession.reload
- `docs/extensions.md` — 用户文档与生命周期图

以上路径均相对于 `packages/coding-agent/`。
