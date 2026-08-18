# Pi 五层架构逐层详解：文章说法与源码实证

> - 源码基准：`github.com/earendil-works/pi` main 分支，2026-08-17 抓取
> - 文章基准：[dg-ai-notes 第 3 章 Agent Loop](https://dg-ai-notes.pages.dev/modules/ch03-agent-loop/)（基于 v0.80.2）、[pi-book](https://zhanghandong.github.io/pi-book/)（基于 v0.66.0 对照 v0.82.1）
> - 用途：给 Koko Runtime 迭代提供逐层对照依据，见 [Koko Runtime 迭代设计](./koko-pi-inspired-runtime-design.md)
> - 注意：文章讲的是 `badlogic/pi-mono`，仓库已迁移到 `earendil-works/pi`，本文所有行号以当前 main 为准

## 0. 这张图对应到什么代码

常见的那张五层图：

```text
用户 / CLI / Web / Slack
          ↓
产品层：会话树、压缩、Prompt、Skill、Extension
          ↓
Agent：保存消息、队列、运行状态
          ↓
agentLoop：调模型 → 执行工具 → 把结果交回模型
          ↓
pi-ai：统一不同 LLM Provider 的消息与流式事件
```

落到真实仓库：

| 图上的层 | 真实位置 | 规模 | 核心文件 |
| --- | --- | --- | --- |
| 宿主 | `packages/tui`、`packages/server`、`packages/client`、`packages/protocol`，Slack 在另一个仓库 `earendil-works/pi-chat` | 92 / 31 / 23 / 17 个文件 | — |
| 产品层 | `packages/coding-agent` | 649 个文件 | `src/core/sdk.ts`（组合根）、`src/core/agent-session.ts`（3344 行） |
| Agent | `packages/agent/src/agent.ts` | 592 行 | 一个类 |
| agentLoop | `packages/agent/src/agent-loop.ts` | 796 行 | 一组自由函数 |
| pi-ai | `packages/ai` | 327 个文件 | `src/types.ts`（830 行）+ `src/api/*`（每个 provider API 一个适配器） |

两个数字最能说明这套架构的取向：**内核两个文件 1388 行，产品层 649 个文件**。所谓"small core"指的是核心承担的职责少、变化原因少，不是代码少。

依赖方向严格单向向下：`agent` 只 import `pi-ai`，`coding-agent` import 两者，`pi-ai` 谁也不认识。

---

## 第 5 层 · pi-ai：统一 Provider 的消息与流式事件

### 它守的不变量

无论下游是 Anthropic Messages、OpenAI Responses、Google Vertex、Bedrock Converse 还是本地 llama.cpp，上层看到的都是同一组类型。`packages/ai/src/api/` 下每个 API 一个适配器文件（`anthropic-messages.ts`、`openai-responses.ts`、`bedrock-converse-stream.ts`……），`packages/ai/src/providers/` 下每个厂商一个配置文件。适配器负责把厂商的 SSE 协议翻译成统一事件，**这是典型的反腐层（Anti-Corruption Layer）**：厂商协议的怪癖不许穿透到 agent 层。

### 消息模型（`src/types.ts:338-455`）

内容块只有四种：

```typescript
TextContent      { type: "text";     text: string; textSignature?: string }
ThinkingContent  { type: "thinking"; thinking: string; thinkingSignature?: string; redacted?: boolean }
ImageContent     { type: "image";    data: string; mimeType: string }
ToolCall         { type: "toolCall"; id: string; name: string; arguments: Record<string, any> }
```

消息只有三种，`Message = UserMessage | AssistantMessage | ToolResultMessage`（`:455`）。

值得注意的字段：

- `AssistantMessage.stopReason`（`:393`）：`"pending" | "stop" | "length" | "toolUse" | "error" | "aborted" | "deferred"`。**整个 Loop 的控制流最终由它和 content 里有没有 toolCall 块共同决定。**
- `ThinkingContent.thinkingSignature` / `ToolCall.thoughtSignature`：厂商私有的不透明签名（OpenAI 的 reasoning item ID、Google 的 thought signature）。这类字段无法被抽象掉，pi 的做法是**显式留槽位、原样透传**，而不是假装不存在。这是反腐层的诚实之处：能统一的统一，不能统一的暴露成命名清楚的可选字段。
- `Usage`（`:370-391`）：`input / output / cacheRead / cacheWrite / cacheWrite1h? / reasoning? / totalTokens` 加一个平行的 `cost` 明细。注释明确说明 `reasoning` 是 `output` 的子集、`cacheWrite1h` 是 `cacheWrite` 的子集——**只有 Anthropic 报这个拆分**。成本核算在这一层就完成，上层不需要认识各家计价规则。

### 流式事件协议（`src/types.ts:523-539`）

```typescript
type AssistantMessageEvent =
  | { type: "start";          partial: AssistantMessage }
  | { type: "text_start"    | "text_delta"    | "text_end";     contentIndex; partial }
  | { type: "thinking_start"| "thinking_delta"| "thinking_end"; contentIndex; partial }
  | { type: "toolcall_start"| "toolcall_delta"| "toolcall_end"; contentIndex; partial }
  | { type: "done";  reason: "stop"|"length"|"toolUse"|"deferred"; message: AssistantMessage }
  | { type: "error"; reason: "aborted"|"error";                    error:   AssistantMessage }
```

两个设计决定值得注意：

**1. 每个增量事件都携带 `partial` 全量快照，而不只是 delta。** 消费方不需要自己维护累加状态机——想要增量就读 `delta`，想要当前完整消息就读 `partial`。这个选择让上层的流式处理代码短到不可思议（见第 4 层）。

**2. 失败是事件，不是异常。** `StreamFn` 的契约写在 `packages/agent/src/types.ts:22-27`：

```
- Must not throw or return a rejected promise for request/model/runtime failures.
- Failures must be encoded in the returned stream via protocol events and a
  final AssistantMessage with stopReason "error" or "aborted" and errorMessage.
```

一次请求失败，得到的是一条 `stopReason: "error"` 的完整 `AssistantMessage`，它能进消息历史、能被持久化、能被 UI 渲染、能被重试逻辑检查。**如果失败走 throw，它就成了一个不在会话记录里的幽灵。** 这条契约是整套架构能做到"运行过程完全可观察"的地基。

---

## 第 4 层 · agentLoop：调模型 → 执行工具 → 把结果交回模型

### 它守的不变量

**无状态。** 全文 796 行没有一个模块级可变变量，所有状态从参数进、从返回值出：

```typescript
// agent-loop.ts:31-37
export function agentLoop(
  prompts: AgentMessage[],
  context: AgentContext,      // { systemPrompt, messages, tools }
  config: AgentLoopConfig,    // 模型 + 一组回调
  signal: AbortSignal | undefined,
  streamFn: StreamFn,
): EventStream<AgentEvent, AgentMessage[]>
```

这带来的直接好处是**可测试性**：给一个假的 `streamFn`，整个循环就能脱离真实 LLM、数据库和 UI 单独跑。

### 双层循环（`agent-loop.ts:155-275`）

```
外层 while (true)                             ← followUp 续命
  内层 while (hasMoreToolCalls || pendingMessages.length > 0)
      ├─ emit turn_start（首轮跳过，因为 runAgentLoop 已发过）
      ├─ 注入 pendingMessages（steering）
      ├─ streamAssistantResponse()            ← 调模型
      ├─ stopReason 是 error/aborted → 硬停止，直接 return
      ├─ 有 toolCall → 执行工具，结果 push 进 context 和 newMessages
      ├─ emit turn_end
      ├─ prepareNextTurn()                    ← 可换 context / model / thinkingLevel
      ├─ shouldStopAfterTurn() → emit agent_end, return
      └─ pendingMessages = getSteeringMessages()
  ─ getFollowUpMessages() 有货 → pendingMessages = 它, continue 外层
  ─ 否则 break
emit agent_end
```

内层管"这一轮还没干完"，外层管"本来要停了，但又有新活"。区分 steering 和 followUp 的是**检查时机**：

| | steering | followUp |
| --- | --- | --- |
| 检查点 | 进内层循环前（`:167`）+ 每圈结尾（`:259`） | 内层循环全部退出后（`:263`） |
| 语义 | 紧急插队，在工具执行间隙插入 | 排队等叫号，等当前任务全干完 |
| 典型场景 | 用户在 Agent 干活时又输入了指令 | 系统追加"顺便跑个测试" |

### 硬停止与 terminate 的非对称

**硬停止**（`:196-200`）：`stopReason` 是 `error` 或 `aborted`，立刻 `turn_end` + `agent_end` 然后 return。不执行工具、不查 steering、不查 followUp。模型调用本身失败了，继续跑没有意义。

**terminate 是一票否决制的反面**（`:582-584`）：

```typescript
function shouldTerminateToolBatch(finalizedCalls: FinalizedToolCallOutcome[]): boolean {
  return finalizedCalls.length > 0 && finalizedCalls.every((f) => f.result.terminate === true);
}
```

用 `every` 不用 `some`：**必须这批工具全部要求停止，Loop 才真的停。** 只要还有一个工具在正常工作，循环就不中断。

而**串行判定用的是 `some`**（`:419-421`）：

```typescript
const hasSequentialToolCall = toolCalls.some(
  (tc) => currentContext.tools?.find((t) => t.name === tc.name)?.executionMode === "sequential",
);
```

一批里只要有一个工具声明了 `sequential`，整批都串行。两处相反的选择服务同一个原则：**在"多等一会"和"可能出错"之间，永远选多等一会。**

### 流式响应的原地替换（`:281-372`）

```typescript
case "start":
    partialMessage = event.partial;
    context.messages.push(partialMessage);          // 先塞一个空壳
    break;
case "text_delta": /* …以及其余 8 种增量事件… */
    partialMessage = event.partial;
    context.messages[context.messages.length - 1] = partialMessage;   // ★ 覆盖最后一条
    await emit({ type: "message_update", assistantMessageEvent: event, message: {...partialMessage} });
    break;
case "done": case "error":
    const finalMessage = await response.result();
    context.messages[context.messages.length - 1] = finalMessage;      // ★ 用终态覆盖
    return finalMessage;
```

消息**数量**始终不变，最后一条的**内容**在长大。UI 通过 `message_update` 拿到 `partial` 就能逐字渲染，而 `context.messages` 任何时刻都是一个结构完整、可直接送去转换的数组。第 5 层"每个事件都带 partial"的决定，在这里兑现成了 9 个 case 共用 3 行代码。

注意 `addedPartial` 标志（`:315`、`:349-356`）：如果流在 `start` 之前就 `error` 了，空壳从未 push 过，此时要走 `push` 而不是覆盖，并补发一个 `message_start`。这个分支保证了**事件序列在任何失败路径下都成对**。

### 一次 LLM 调用前发生的四件事（`:288-312`）

```typescript
let messages = context.messages;
if (config.transformContext) messages = await config.transformContext(messages, signal);  // ① AgentMessage → AgentMessage
const llmMessages = await config.convertToLlm(messages);                                  // ② AgentMessage → Message
const llmContext: Context = { systemPrompt, messages: llmMessages, tools };                // ③ 组装
const resolvedApiKey = (config.getApiKey ? await config.getApiKey(...) : undefined) || config.apiKey;  // ④ 每轮重解析 key
```

第 ① 步和第 ② 步的分工是这一层最容易被忽略的设计：`transformContext` 工作在**产品自定义的消息类型**上（压缩、注入上下文），`convertToLlm` 才是**降级到 LLM 只认识的三种消息**的边界。产品层可以往历史里塞 `bashExecution`、`custom`、`compactionSummary` 这些 LLM 根本不认识的消息，由 `convertToLlm` 决定它们翻译成什么、或者干脆丢弃。

第 ④ 步 `getApiKey` 每轮重新解析——因为工具执行阶段可能长达几分钟，OAuth token（GitHub Copilot 之类）会在这期间过期。

### 工具三段管道（`:600-758`）

```
prepare  ──→  execute  ──→  finalize
```

**prepare（`:600-668`）** 做五件事，任何一件失败都返回 `kind: "immediate"` 的错误结果，不会抛出去：

1. 按名字找工具，找不到 → `Tool ${name} not found`
2. `tool.prepareArguments?.()`——给旧参数格式一个兼容垫片
3. `validateToolArguments()`——schema 校验（typebox）
4. `config.beforeToolCall?.()`——可以 `{ block: true, reason }` 拦截
5. 前后各查一次 `signal?.aborted`

**execute（`:670-711`）** 只做一件事：调 `tool.execute(id, args, signal, onUpdate)`。这里有个细节值得学——`acceptingUpdates` 闸门：

```typescript
let acceptingUpdates = true;
const result = await prepared.tool.execute(..., (partialResult) => {
    if (!acceptingUpdates) return;                    // ← 工具结束后迟到的 update 直接丢弃
    updateEvents.push(Promise.resolve(emit({ type: "tool_execution_update", ... })));
});
acceptingUpdates = false;
await Promise.all(updateEvents);                      // ← 但已经发出的要等它们完成
```

一个写得不好的工具可能在 promise resolve 之后还调 `onUpdate`。闸门保证这些迟到的回调不会污染事件流，同时 `Promise.all` 保证已经进入队列的 update 事件在 `tool_execution_end` 之前排空。**顺序保证不能指望工具作者，只能由管道自己兜住。**

**finalize（`:713-758`）** 跑 `afterToolCall` 钩子，做**字段级覆盖**而不是深合并：

```typescript
result = {
  ...result,
  content:   afterResult.content   ?? result.content,
  details:   afterResult.details   ?? result.details,
  usage:     afterResult.usage     ?? result.usage,
  terminate: afterResult.terminate ?? result.terminate,
};
```

`packages/agent/src/types.ts:71-95` 把这条语义写进了注释：*"There is no deep merge for `content`, `details`, or `usage`."* 钩子的合并规则是**接口的一部分**，不是实现细节。

### 并行的三阶段（`:489-554`）

```
阶段 1  prepare  顺序执行     ← 校验和 beforeToolCall 不能并行：B 被拦截了，C 就不该跑
阶段 2  execute  Promise.all  ← 只有真正的 I/O 并行
阶段 3  结果发射  两种顺序     ← tool_execution_end 按完成顺序；toolResult 消息按调用顺序
```

阶段 3 的双顺序是关键：`tool_execution_end` 按完成顺序发，UI 可以谁先完成谁先消失转圈；但进入消息历史的 `ToolResultMessage` **必须按 assistant 消息里 toolCall 的原始顺序**，否则模型下一轮看到的上下文顺序就是乱的。

### 一个文章里没有的新防御：`length` 截断（`:207-214`、`:381-406`）

```typescript
const executedToolBatch =
  message.stopReason === "length"
    ? await failToolCallsFromTruncatedMessage(toolCalls, emit)   // 全部失败，一个都不执行
    : await executeToolCalls(currentContext, message, config, signal, emit);
```

源码注释解释了为什么：流式的工具调用参数是用**尽力而为的 JSON 抢救解析器**收尾的，所以一条被 token 上限截断的消息，可能产出「能解析、能通过 schema 校验、但内容悄悄不完整」的工具调用。想象一个 `bash` 调用的 `command` 参数被截成 `rm -rf /tmp/build-artifacts` 前半截。**校验通过不等于语义完整**，所以整批拒绝执行，返回错误让模型重发。

这是 v0.80.2 之后加的防御，dg-ai-notes 第 3 章没有涵盖。

### 事件表（`packages/agent/src/types.ts:428-443`）

```typescript
agent_start / agent_end{messages}
turn_start  / turn_end{message, toolResults}
message_start{message} / message_update{message, assistantMessageEvent} / message_end{message}
tool_execution_start{toolCallId, toolName, args}
tool_execution_update{..., partialResult}
tool_execution_end{toolCallId, toolName, result, isError}
```

十种事件，覆盖三个嵌套的生命周期（agent → turn → message/tool）。注意 `message_update` 是唯一带 `assistantMessageEvent` 的——它把第 5 层的原始流式事件原样透传上来，UI 想做精细渲染（比如区分 thinking 和 text）时不必反推。

---

## 第 3 层 · Agent：保存消息、队列、运行状态

`agent.ts` 592 行，一个类。它是**第 4 层那个无状态发动机的有状态外壳**。

### 状态的四个部分（`agent.ts:174-177`、`:204`）

```typescript
private _state: MutableAgentState;               // systemPrompt / model / thinkingLevel / tools / messages / isStreaming / pendingToolCalls
private readonly listeners = new Set<...>();     // 订阅者
private readonly steeringQueue: PendingMessageQueue;
private readonly followUpQueue: PendingMessageQueue;
private activeRun?: ActiveRun;                   // { promise, resolve, abortController }
```

`MutableAgentState`（`:68-95`）用 getter/setter 包住 `tools` 和 `messages`，赋值时 `slice()` 拷贝顶层数组。外部拿到的引用改不动内部状态。

### 双队列与 drain 模式（`:125-159`）

```typescript
drain(): AgentMessage[] {
  if (this.mode === "all") { const d = this.messages.slice(); this.messages = []; return d; }
  const first = this.messages[0];
  if (!first) return [];
  this.messages = this.messages.slice(1);
  return [first];                                 // one-at-a-time：一次只放一条
}
```

`QueueMode` 有 `"all"` 和 `"one-at-a-time"` 两种，默认后者（`:231-232`）。一次只放一条意味着用户连打三条指令时，Agent 会在三个不同的 turn 边界分别处理，而不是一股脑塞进同一次调用——每条指令都能看到上一条的执行结果。

### 唯一活跃 run（`:486-509`）

```typescript
private async runWithLifecycle(executor: (signal: AbortSignal) => Promise<void>): Promise<void> {
  if (this.activeRun) throw new Error("Agent is already processing.");
  const abortController = new AbortController();
  this.activeRun = { promise, resolve: resolvePromise, abortController };
  this._state.isStreaming = true;
  try { await executor(abortController.signal); }
  catch (error) { await this.handleRunFailure(error, abortController.signal.aborted); }
  finally { this.finishRun(); }
}
```

`prompt()` 在已有 run 时不是排队，而是**抛错并告诉你该用什么**（`:351-355`）：

> `"Agent is already processing a prompt. Use steer() or followUp() to queue messages, or wait for completion."`

错误信息直接指向正确 API，这是接口设计的一部分。

### `continue()` 的三段回退（`:361-388`）

最后一条是 assistant 消息时不能直接续（LLM 会拒绝），此时按序尝试：

1. drain steering 队列 → 有货就当新 prompt 跑，并设 `skipInitialSteeringPoll`（避免刚取出的消息被 loop 再取一次）
2. drain followUp 队列 → 有货就跑
3. 都没有 → 抛 `"Cannot continue from message role: assistant"`

### 失败也要走完整事件序列（`:511-527`）

```typescript
private async handleRunFailure(error: unknown, aborted: boolean): Promise<void> {
  const failureMessage = {
    role: "assistant", content: [{ type: "text", text: "" }],
    api, provider, model, usage: EMPTY_USAGE,
    stopReason: aborted ? "aborted" : "error",
    errorMessage: error instanceof Error ? error.message : String(error),
    timestamp: Date.now(),
  } satisfies AgentMessage;
  await this.processEvents({ type: "message_start", message: failureMessage });
  await this.processEvents({ type: "message_end",   message: failureMessage });
  await this.processEvents({ type: "turn_end",      message: failureMessage, toolResults: [] });
  await this.processEvents({ type: "agent_end",     messages: [failureMessage] });
}
```

即使是 loop 内部意外抛出的异常，Agent 也**合成一条 assistant 消息**并补齐 `message_start → message_end → turn_end → agent_end` 四个事件。订阅者永远不会遇到"发了 agent_start 却等不到 agent_end"的悬挂状态。这和第 5 层"失败编码进事件流"是同一条原则在不同层的复现。

### 事件处理是 reducer + 顺序广播（`:544-591`）

```typescript
private async processEvents(event: AgentEvent): Promise<void> {
  switch (event.type) {
    case "message_start": case "message_update": this._state.streamingMessage = event.message; break;
    case "message_end":   this._state.streamingMessage = undefined;
                          this._state.messages.push(event.message); break;      // ← 消息在这里才进历史
    case "tool_execution_start": /* pendingToolCalls.add */ break;
    case "tool_execution_end":   /* pendingToolCalls.delete */ break;
    case "turn_end": if (event.message.errorMessage) this._state.errorMessage = ...; break;
  }
  const signal = this.activeRun?.abortController.signal;
  if (!signal) throw new Error("Agent listener invoked outside active run");
  for (const listener of this.listeners) await listener(event, signal);          // ← 顺序 await
}
```

两点：

**监听器是顺序 await 的，不是 fire-and-forget。** 这意味着一个慢监听器会拖慢整个循环——代价明确，换来的是`agent_end` 之后的持久化、UI 刷新都确定已完成。

**`waitForIdle()` 等的是 listener 结算，不是 `agent_end` 事件。** `types.ts:346-351` 的注释写得很清楚：*"This remains true until awaited `agent_end` listeners settle."* `agent_end` 只表示 loop 不再发事件，Agent 变 idle 要等所有监听器跑完 + `finishRun()` 清完状态。这个区分在写"运行结束后自动做某事"的逻辑时至关重要。

### 这一层做的翻译（`:445-484`）

`createLoopConfig()` 把 Agent 的字段翻译成 loop 的回调：

```typescript
getSteeringMessages: async () => {
  if (skipInitialSteeringPoll) { skipInitialSteeringPoll = false; return []; }
  return this.steeringQueue.drain();
},
getFollowUpMessages: async () => this.followUpQueue.drain(),
shouldStopAfterTurn: shouldStopAfterTurn ? async (ctx) => await shouldStopAfterTurn(ctx, this.signal) : undefined,
```

第 4 层不知道有"队列"这个东西，它只知道有个函数能问出"有没有待插入的消息"。**队列是第 3 层的实现选择，不是内核概念。**

---

## 第 2 层 · 产品层：会话树、压缩、Prompt、Skill、Extension

649 个文件。这一层的量级本身就是论据：**所有跟"这是个编码 CLI"有关的决定都在这里，往下一层都看不见。**

### 组合根：`src/core/sdk.ts:297-363`

整个系统只有一处 `new Agent({...})`，参数就是产品层往内核挂的全部接线：

```typescript
agent = new Agent({
  initialState: { systemPrompt: "", model, thinkingLevel, tools: [] },
  convertToLlm: convertToLlmWithBlockImages,                        // 反腐 + blockImages 设置
  streamFn: async (model, context, options) => modelRuntime.streamSimple(model, context, {
      ...options, timeoutMs, maxRetries, websocketConnectTimeoutMs,
      transformHeaders: async (h) => runner.emitBeforeProviderHeaders(h),   // → 扩展 before_provider_headers
  }),
  onPayload:  async (payload) => runner.emitBeforeProviderRequest(payload), // → 扩展 before_provider_request
  onResponse: async (res)     => runner.emit({ type: "after_provider_response", status, headers }),
  transformContext: async (messages) => runner.emitContext(messages),       // → 扩展 context
  steeringMode:  settingsManager.getSteeringMode(),
  followUpMode:  settingsManager.getFollowUpMode(),
  transport, thinkingBudgets, maxRetryDelayMs, sessionId,
});
```

**内核的每一个回调槽，产品层都用来接扩展事件。** `transformContext` → `context` 事件、`beforeToolCall` → `tool_call` 事件、`afterToolCall` → `tool_result` 事件。内核提供机制，产品层决定策略，扩展决定具体行为——三级分离。

### AgentSession：3344 行的产品外壳

`src/core/agent-session.ts` 是产品层的主类。它挂在 Agent 上的钩子：

**`_installAgentToolHooks()`（`:479-533`）** 把 loop 的两个工具钩子接到扩展系统：

```typescript
this.agent.beforeToolCall = async ({ toolCall, args }) => {
  const runner = this._extensionRunner;
  if (!runner.hasHandlers("tool_call")) return undefined;      // ← 没有 handler 就零开销
  return await runner.emitToolCall({ type: "tool_call", toolName, toolCallId, input: args });
};

this.agent.afterToolCall = async ({ toolCall, args, result, isError }) => {
  const hookResult = runner.hasHandlers("tool_result") ? await runner.emitToolResult({...}) : undefined;
  const normalizedContent = await normalizeToolResultImages(hookResult?.content ?? result.content ?? [], {...});
  //   ↑ 在扩展钩子之后归一化，所以扩展注入或替换的图片也会被处理
  ...
};
```

`hasHandlers()` 短路是个小而重要的细节：没人订阅时，钩子链路的开销降到一次 Set 查询。

**`_installAgentNextTurnRefresh()`（`:535-556`）** 用 `prepareNextTurnWithContext` 在**每一轮开始前**重新灌入 systemPrompt、tools、model、thinkingLevel：

```typescript
this.agent.prepareNextTurnWithContext = async (turn, signal) => {
  const previousSnapshot = await previousPrepareNextTurnWithContext?.(turn, signal);
  return {
    ...previousSnapshot,
    context: { ...previousContext,
               systemPrompt: this._systemPromptOverride ?? this._baseSystemPrompt,
               tools: this.agent.state.tools.slice() },
    model: this.agent.state.model,
    thinkingLevel: this.agent.state.thinkingLevel,
  };
};
```

这就是为什么扩展可以在会话进行到一半注册新工具、用户可以中途 `/model` 换模型——**每一轮的配置都是重新取的快照，而不是 run 开始时冻结的**。注意它保留并调用了 `previousPrepareNextTurnWithContext`，是叠加而非覆盖。

**`_handleAgentEvent()`（`:610-681`）** 是事件的三段分发，顺序有讲究：

```typescript
await this._emitExtensionEvent(event);       // ① 先给扩展（它们可能要修改状态）
this._emit(event.type === "agent_end" ? { ...event, willRetry } : event);   // ② 再给 UI 监听器
if (event.type === "message_end") {          // ③ 最后落盘
  if (event.message.role === "custom")       this.sessionManager.appendCustomMessageEntry(...);
  else if (role is user|assistant|toolResult) this.sessionManager.appendMessage(event.message);
}
```

`agent_end` 事件被加了一个 `willRetry` 字段——UI 需要知道"这次结束是真结束还是马上要自动重试"，才能决定要不要收起转圈动画。这是产品层给内核事件**加语义**而不改内核的例子。

### 压缩不在 Loop 里（`:1063-1104`）

这是文章和源码差最远的一处。文章说压缩通过 `shouldStopAfterTurn` 触发；实际上 **coding-agent 完全没有使用 `shouldStopAfterTurn`**（全仓库仅 `agent-loop.ts:248` 一处定义点调用）。真实做法是：

```typescript
private async _runAgentPrompt(messages: AgentMessage | AgentMessage[]): Promise<void> {
  this._isAgentRunActive = true;
  try {
    await this.agent.prompt(messages);
    while (await this._handlePostAgentRun()) {     // ← 一次完整 run 结束之后
      await this.agent.continue();                 // ← 再开一次 run
    }
  } finally { ...; await this._emitAgentSettled(); }
}

private async _handlePostAgentRun(): Promise<boolean> {
  const msg = this._lastAssistantMessage;
  if (!msg) return false;
  if (this._isRetryableError(msg) && (await this._prepareRetry(msg))) return true;   // ① 自动重试
  if (await this._checkCompaction(msg)) return true;                                 // ② 压缩后续跑
  return this.agent.hasQueuedMessages();                                             // ③ agent_end 期间新入队的消息
}
```

**重试、压缩、续跑三件事全在 Loop 之外，用「run 完了再判断要不要开下一个 run」实现。** 内核只提供 `prompt()` / `continue()` 两个入口，产品层用一个 while 循环把它们串成任意复杂的策略。

这也解释了 `agent_settled` 这个产品层独有的事件（`:596-604`）：`agent_end` 是内核的"这一次 run 结束"，`agent_settled` 才是产品层的"重试、压缩、后续队列全部处理完，真的空闲了"。**两个"结束"概念必须分开，否则 UI 会在自动压缩期间误报完成。**

### 会话树：JSONL + `id`/`parentId`

`docs/session-format.md` 定义的格式：

```typescript
interface SessionEntryBase {
  type: string;
  id: string;              // 8 字符 hex
  parentId: string | null; // 首条为 null
  timestamp: string;       // ISO
}
```

文件位置 `~/.pi/agent/sessions/--<cwd 路径>--/<timestamp>_<uuid>.jsonl`，当前版本 v3（v1 线性 → v2 树 → v3 把 `hookMessage` 角色改名 `custom`，加载时自动迁移）。

条目类型：`message` / `model_change` / `thinking_level_change` / `compaction` / `branch_summary` / `custom` / `custom_message` / `label` / `session_info`。

三个设计点：

**1. 只追加，不修改。** 同一个 `parentId` 有多个子节点就是分叉。`/fork`、`/clone`、`/tree` 都是在这棵树上导航，不删除任何历史。

**2. `custom` 和 `custom_message` 的区分。** 前者是扩展的状态持久化，**不进 LLM 上下文**；后者是扩展注入的消息，**进 LLM 上下文**。同一个扩展存 todo 列表用前者，往对话里插一句提示用后者。这个区分让"扩展有状态"和"扩展影响模型"变成两件独立的事。

**3. `compaction` 条目的 `retainedTail`。** 新版压缩条目直接把压缩后保留的消息数组**内嵌进条目**，而不是用旧版的 `firstKeptEntryId` 指针。理由写在文档里：这样重建上下文时不必回溯压缩点之前的旧条目。**用空间换取"从任一 checkpoint 单点恢复"的能力。**

对应的 `AgentMessage` 联合类型也被产品层扩展了：

```typescript
type AgentMessage = UserMessage | AssistantMessage | ToolResultMessage
                  | BashExecutionMessage | CustomMessage | BranchSummaryMessage | CompactionSummaryMessage;
```

后四种 LLM 完全不认识，靠 `core/messages.ts:148` 的 `convertToLlm()` 在送去模型前翻译或过滤。**这就是第 4 层留 `convertToLlm` 这个槽位的全部理由。**

### Extension：微内核架构

`docs/extensions.md` 的生命周期图精确显示了产品层如何在内核事件上**叠加**自己的事件：

```
用户发 prompt
  ├─► (先查扩展命令，命中则绕过整个 loop)
  ├─► input                    ← 产品层独有，可拦截/转换/直接处理
  ├─► (skill / prompt template 展开)
  ├─► before_agent_start       ← 产品层独有，可注入消息、改 systemPrompt
  ├─► agent_start              ← 内核事件
  │   ┌── turn ──────────────────────────────┐
  │   ├─► turn_start                          ← 内核
  │   ├─► context                             ← 产品层（挂在 transformContext）
  │   ├─► before_provider_headers             ← 产品层（挂在 transformHeaders）
  │   ├─► before_provider_request             ← 产品层（挂在 onPayload）
  │   ├─► after_provider_response             ← 产品层（挂在 onResponse）
  │   ├─► tool_execution_start                ← 内核
  │   ├─► tool_call         (可 block)        ← 产品层（挂在 beforeToolCall）
  │   ├─► tool_result       (可改)            ← 产品层（挂在 afterToolCall）
  │   ├─► tool_execution_end                  ← 内核
  │   └─► turn_end                            ← 内核
  ├─► agent_end                               ← 内核
  └─► agent_settled                           ← 产品层：重试/压缩/队列都完了
```

外加会话级事件：`session_start` / `session_before_switch` / `session_before_fork` / `session_before_compact` / `session_compact` / `session_before_tree` / `session_tree` / `session_shutdown` / `project_trust` / `resources_discover` / `model_select` / `thinking_level_select`。

**观察与拦截是分开的**：`session_before_*` 系列可以取消或定制，`session_*` 系列只是通知。`tool_call` 返回 `{ block: true, reason }` 能拦截，`tool_execution_start` 只能看。

扩展能力（`ExtensionAPI`）：`pi.on()` 订阅事件、`pi.registerTool()` 注册 LLM 可调用的工具、`pi.registerCommand()` 注册 `/命令`、`pi.appendEntry()` 持久化状态、`pi.registerEntryRenderer()` 自定义渲染。加载位置 `~/.pi/agent/extensions/*.ts`（全局）和 `.pi/extensions/*.ts`（项目级，**需项目被信任后才加载**）。

值得注意的是 pi 的安全立场，README 写得很直白：pi **不内置权限系统**，默认以启动用户的权限运行；需要边界就上容器或沙箱。这是"机制与策略分离"推到极致的结果——权限确认在 CLI 是弹窗、在 Slack 是消息审批、在 CI 应该完全禁止，所以内核只提供 `beforeToolCall()` 这个机制，策略交给扩展和宿主。

---

## 第 1 层 · 宿主：CLI / TUI / Web / Slack

宿主只做两件事：**消费事件流**、**调用产品层 API**。

| 宿主 | 位置 |
| --- | --- |
| CLI + TUI | `packages/coding-agent/src/main.ts` + `packages/tui`（差分渲染的终端 UI 库） |
| RPC / headless | `packages/coding-agent/src/rpc-entry.ts` + `docs/rpc.md` |
| Server / Client / Protocol | `packages/server`、`packages/client`、`packages/protocol` |
| Slack / 聊天自动化 | **另一个仓库** `earendil-works/pi-chat` |

Slack 在独立仓库这件事本身就是分层有效性的证明：**它不需要修改 pi 主仓库的任何一行代码就能成为一个宿主。**

---

## 三处文章与源码不一致的地方

| # | 文章说法 | 源码实际 | 影响 |
| --- | --- | --- | --- |
| 1 | `shouldStopAfterTurn` 是产品层的安全阀，用于上下文快满时停下触发压缩 | coding-agent **完全没用**这个钩子。压缩在 `_handlePostAgentRun()` 里、一次 run 结束之后做，然后 `agent.continue()` 续跑 | 照文章实现会把压缩写进 turn 边界，拿不到「整次 run 的最终状态」，也无法和自动重试共用同一个决策点 |
| 2 | 未涵盖 | `stopReason === "length"` 时整批工具调用直接失败，一个都不执行（`agent-loop.ts:207-214`） | 这是防「参数被截断但恰好通过 schema 校验」的关键防御，实现 Loop 时容易漏 |
| 3 | 仓库是 `badlogic/pi-mono` | 已迁移到 `earendil-works/pi`，包名 `@earendil-works/pi-ai` / `pi-agent-core` / `pi-coding-agent` | 文章里的所有源码链接和行号都需要重新核对 |

---

## 这张五层图正在发生的变化：AgentHarness

`packages/agent/src/harness/` 下现在有 `session/`、`skills.ts`、`system-prompt.ts`、`tools/`、`compaction/`——**和 coding-agent 里的同名模块并存**。配套的 `packages/agent/docs/harness.md` 是一份 2941 行的实现规格，开头一句话定位：

> *"A durable runtime for agent conversations. It persists conversation and operation state so interrupted work can resume without repeating settled effects."*

它引入的概念比现在的产品层严肃得多：

- **三个存储**：`entries`（会话树，write-once append-only）、`registers`（可变命名空间键值，当前状态）、`usage ledger`（append-only 成本流水）。规格明确写"每个 payload 只可能在这三者之一，没有第四个地方"。
- **Lane**：指向树上某个叶子的命名游标。每个 session 至少有 `main`。**Slack 线程、子 agent、并行任务各占一个 lane，共享同一棵历史树**。文档里第一个完整示例就是 Slack 线程。
- **持久程序计数器**：每一步之后覆写 `op.state/{operationId}` 这一个 register，存放操作的**完整当前状态**。崩溃恢复不重放日志、不从缺失推断位置，直接读这个 register 然后 switch。
- **效果三明治**：provider 请求和真实工具调用被夹在两次提交之间——`commit(意图，预留好输出的 id) → 执行 → commit(输出 + usage + 下一状态)`。工具可以声明 `replay: "never" | "safe"`，崩溃后重启时，`never` 的工具不会被重跑，而是补一条合成的 interrupted 结果，保证「每个 tool call 都有结果」这个不变量。

方向很清楚：**"产品层：会话树"这一条正在往下沉。** 会话树、压缩、崩溃恢复、多 lane 并行从 coding-agent 移到 agent 包，成为任何宿主都能复用的持久化运行时；coding-agent 保留的是真正跟"编码 CLI 这个产品"绑定的东西。

如果按现在的 main 分支重画那张图，中间会多一层：

```text
用户 / CLI / Web / Slack
          ↓
产品层（coding-agent）：Prompt、Skill、Extension、TUI 渲染、设置
          ↓
AgentHarness（agent/harness）：会话树、lane、压缩、崩溃恢复、三存储
          ↓
Agent：保存消息、队列、运行状态
          ↓
agentLoop：调模型 → 执行工具 → 把结果交回模型
          ↓
pi-ai：统一不同 LLM Provider 的消息与流式事件
```

---

## 对 Koko 的对照

| Pi | Koko 当前 | 差距 |
| --- | --- | --- |
| `packages/ai` 统一 Message / AssistantMessageEvent / StopReason / Usage | `koko_pi_agent/runtime/model_stream.py`、`events.py` | Provider 抽象规模差一个量级，但不变量的形状一致 |
| `agent-loop.ts` 无状态 + 全部通过回调注入 | `koko_pi_agent/runtime/agent_loop.py`（598 行） | 需核对：是否还有状态挂在 loop 上 |
| `Prepare → Execute → Finalize` 三段管道 | `koko_pi_agent/runtime/tool_pipeline.py`（499 行） | 已有对应实现 |
| `Agent` 有状态外壳 + 双队列 + 单 activeRun | `koko_pi_agent/runtime/agent_run.py`、`run_control.py` | 已有对应实现 |
| `sdk.ts` 单一组合根 | `koko_pi_agent/runtime/agent_runtime.py`（166 行） | 已有对应实现 |
| `prepareNextTurn` 每轮刷新 systemPrompt/tools/model | `koko_pi_agent/runtime/turn_preparer.py`（163 行） | 已有对应实现（阶段 2B） |
| 会话树 `id`/`parentId` JSONL | 当前为线性会话 | **最大的结构性缺口**，见 [pi-agentmessage 分析](../.specstory/history/2026-08-17_03-24-01Z-pi-agentmessage-llm-message.md) |
| 观察（`session_*`）与拦截（`session_before_*`）分离 | HookEngine 未区分 | 见 [pi-agentevent 分析](../.specstory/history/2026-08-17_03-23-44Z-pi-agentevent-observer-publish.md) |
| 每个内核回调槽都接到扩展事件 | ExtensionHost 阶段 2C 进行中 | — |

三条最值得直接借鉴的实现细节：

1. **`agent_end` 与 `agent_settled` 必须是两个事件。** 内核的"这次 run 结束"和产品的"重试压缩队列全清完"混为一谈，UI 状态一定会错。
2. **失败一律编码成消息 + 完整事件序列，不许 throw 穿透。** 第 5 层、第 4 层、第 3 层各自都实现了这条，代价是几十行 boilerplate，换来的是任何失败路径下事件都成对、都可持久化、都可渲染。
3. **`terminate` 用 `every`，`sequential` 用 `some`。** 两处相反的聚合方向，同一个保守原则。

---

## 源码索引

以下行号基于 `earendil-works/pi` main 分支，2026-08-17。

**pi-ai**
- `packages/ai/src/types.ts:338-368` — 四种内容块
- `packages/ai/src/types.ts:370-391` — Usage 与 cost
- `packages/ai/src/types.ts:393` — StopReason
- `packages/ai/src/types.ts:409-455` — 三种消息与 Message 联合
- `packages/ai/src/types.ts:502-513` — Tool / Context
- `packages/ai/src/types.ts:523-539` — AssistantMessageEvent 流式协议

**agentLoop**
- `packages/agent/src/agent-loop.ts:31-93` — agentLoop / agentLoopContinue 入口
- `packages/agent/src/agent-loop.ts:155-275` — runLoop 双层循环
- `packages/agent/src/agent-loop.ts:196-200` — 硬停止
- `packages/agent/src/agent-loop.ts:207-214` — length 截断防御
- `packages/agent/src/agent-loop.ts:281-372` — streamAssistantResponse 原地替换
- `packages/agent/src/agent-loop.ts:381-406` — failToolCallsFromTruncatedMessage
- `packages/agent/src/agent-loop.ts:411-426` — 串并行调度（some 一票否决）
- `packages/agent/src/agent-loop.ts:489-554` — 并行三阶段
- `packages/agent/src/agent-loop.ts:582-584` — terminate（every）
- `packages/agent/src/agent-loop.ts:600-758` — prepare / execute / finalize
- `packages/agent/src/types.ts:22-27` — StreamFn 不许抛异常的契约
- `packages/agent/src/types.ts:149-293` — AgentLoopConfig 全部回调
- `packages/agent/src/types.ts:428-443` — AgentEvent 十种事件

**Agent**
- `packages/agent/src/agent.ts:68-95` — MutableAgentState 拷贝语义
- `packages/agent/src/agent.ts:125-159` — PendingMessageQueue / drain
- `packages/agent/src/agent.ts:348-388` — prompt / continue 的三段回退
- `packages/agent/src/agent.ts:445-484` — createLoopConfig 翻译层
- `packages/agent/src/agent.ts:486-509` — runWithLifecycle
- `packages/agent/src/agent.ts:511-527` — handleRunFailure 合成消息
- `packages/agent/src/agent.ts:544-591` — processEvents reducer

**产品层**
- `packages/coding-agent/src/core/sdk.ts:259-363` — 唯一组合根
- `packages/coding-agent/src/core/agent-session.ts:479-533` — 工具钩子接扩展
- `packages/coding-agent/src/core/agent-session.ts:535-556` — prepareNextTurn 每轮刷新
- `packages/coding-agent/src/core/agent-session.ts:610-681` — 事件三段分发
- `packages/coding-agent/src/core/agent-session.ts:1063-1104` — 重试 / 压缩 / 续跑
- `packages/coding-agent/src/core/messages.ts:148` — convertToLlm 反腐层
- `packages/coding-agent/src/core/extensions/types.ts:670-673, 1065` — ContextEvent
- `packages/coding-agent/docs/session-format.md` — 会话树格式
- `packages/coding-agent/docs/extensions.md` — 扩展生命周期

**演进中**
- `packages/agent/docs/harness.md` — AgentHarness 实现规格（2941 行）
