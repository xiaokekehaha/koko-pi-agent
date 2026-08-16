---
title: 从 Cordis 的时空可组合性到 Python 插件运行时
source: https://www.zhihu.com/question/2071375581464343126/answer/2071477434554249696
source_author: 段小草
reviewed_at: 2026-08-16
python: ">=3.11"
status: 学习笔记与可运行 Demo
---

# 从 Cordis 的时空可组合性到 Python 插件运行时

> 这份文档面向已经学过 Python 函数、类、字典和异常，但对 `asyncio`、依赖注入、插件生命周期还不熟悉的读者。
>
> 阅读来源是知乎回答[《如何评价 DeepSeek 与北大联合发布的新论文，有哪些亮点？对 Agent 发展有什么影响？》](https://www.zhihu.com/question/2071375581464343126/answer/2071477434554249696)。2026-08-16 读取时，知乎直连返回 `403`，最终通过 `r.jina.ai` 提取到正文。关键技术结论又用论文、项目文档和 Python 官方文档进行了交叉检查。

## 0. 这篇文章最值得学什么

这篇文章值得学习的重点，是一种管理动态系统的纪律，和具体模型版本或 TypeScript 写法关系不大：

1. 组件做任何会改变共享环境的事情时，同时登记清理动作。
2. 清理动作按注册顺序的相反方向执行，也就是 LIFO，后进先出。
3. 组件显式声明自己需要什么服务、提供什么服务。
4. 依赖出现时启动消费者，依赖消失时先停止消费者，再停止提供者。
5. 系统恢复的是“外部观察不到差异的状态”，不一定是物理字节完全相同的旧状态。
6. 已经发出的消息、网络请求、扣款等外部影响通常不能真正撤销，只能延迟提交或执行补偿操作。

用 Python 做教学版时，需要把下面这些能力组合起来，`async` 只负责其中一部分：

```text
类型契约 + 服务注册表 + 依赖图 + 生命周期
       + 可逆清理栈 + asyncio 任务管理 + 配置协调
```

`asyncio` 很重要，但它解决的是“等待、并发、取消和异步清理”。可逆性本身来自“所有副作用都经过受控入口，并且每一步都有对应清理”，不是在函数前加上 `async`。

## 1. 文章到底讲了哪些信息

### 1.1 文章的六条主线

| 主线 | 文章给出的信息 | 阅读时要注意什么 |
| --- | --- | --- |
| 项目背景 | Cordis 的思想来自 Koishi 插件生态，后来成为 DeepSeek Harness 的底层元框架 | Koishi 到 Cordis 的工程积累有项目文档支持，但具体人员经历和加入团队的过程，文章明确写的是作者推测 |
| 核心口号 | “一切皆插件，插件皆可逆” | DeepSeek Harness 官方 README 确认“一切皆插件”；“插件皆可逆”是文章对 Cordis 机制的概括 |
| 理论问题 | 动态组合要同时解决时间可组合性和空间可组合性 | 这是论文的正式问题定义，不只是文章作者的类比 |
| 两个机制 | 可逆效应解决卸载后的清理，响应式共效应解决依赖变化 | 两者被统一到 Context 中，由运行时管理 |
| Agent 意义 | 模型、工具、会话、循环、沙箱和 UI 都可以成为可替换组件 | 官方架构文档确认模型适配器、工具注册表、会话日志和 Agent Loop 都是插件 |
| 局限 | 系统边界外的影响不能自动回滚，插件作者仍可能绕开 Context | 这是实际工程边界，不能用“可逆”两个字忽略掉 |

### 1.2 哪些是事实，哪些是观点

#### 已被一手资料支持的信息

- DeepSeek Harness 官方仓库把项目描述为基于 Cordis、采用“一切皆插件”架构的开源 Agent Harness。
- Cordis 论文把动态组合拆成两个正交维度：时间可组合性和空间可组合性。
- 论文用可逆效应、响应式共效应和统一 Context 构造运行时模型。
- DeepSeek Harness 的模型适配器、工具注册表、会话日志和 Agent Loop 都以插件形式参与组合。
- Koishi 文档很早就把 Cordis 描述为元框架，并讨论了可逆副作用、子 Context、服务提供与注入。
- [论文仓库](https://github.com/cordiverse/paper)当前标注的是 2026-08-13、共 88 页的预印本，并明确提示内容仍在修订，具体结果不应脱离版本引用。

#### 知乎作者的分析和推测

- `Cordis > Harness > DeepSeek V4 Flash > DeepSeek V4 Pro` 是作者的价值排序，不是论文结论。
- Yifan Shi 从 Koishi 实践进入 DeepSeek，并把多年工程哲学迁移到 Harness 的完整过程，文章自己标明是猜测。
- Cordis 会显著影响“自进化 Agent 的未来”是方向判断。[论文结尾](https://github.com/cordiverse/paper/blob/main/paper.pdf)把自进化 Agent Harness 称为未来验证方向，并没有声称已经在这类系统中完成充分生产验证。
- Pi Agent 和 Cordis 的对比是有帮助的架构解释，但不能当成两边项目共同发布的正式结论。

学习技术文章时，可以使用一个简单规则：

```text
官方代码和文档说明“现在有什么”；
论文定理说明“在什么前提下能保证什么”；
作者解读说明“这可能意味着什么”。
```

三者都可以有价值，但不能混成同一种证据。

## 2. 先建立抽象模型

### 2.1 动态组合

静态组合是程序启动前已经确定的关系，例如模块导入、函数调用和类继承。

动态组合允许系统运行时加载、卸载、替换和重新配置组件。难点不在“把代码加载进来”，而在组件离开时系统是否仍然正确。

一个普通插件可能做这些事情：

- 注册一个工具；
- 监听一个事件；
- 启动后台任务；
- 打开网络连接；
- 提供数据库服务；
- 修改共享配置；
- 创建子进程。

如果卸载插件时只删除插件对象，上述影响可能仍然留在系统里。真正的插件卸载必须清理它造成的全部内部影响。

### 2.2 时间可组合性：我做过的事能否撤销

时间可组合性关注组件的生命周期。

```text
执行动作：注册工具 -> 监听事件 -> 启动任务
撤销动作：停止任务 -> 取消监听 -> 注销工具
```

为什么撤销顺序相反？因为后执行的动作可能依赖先执行的资源。如果先拆掉底层资源，上层清理代码可能已经无法运行。

在 Python 中，最接近这套思想的标准库工具是：

- `try/finally`；
- 同步和异步上下文管理器；
- `contextlib.ExitStack`；
- `contextlib.AsyncExitStack`；
- 作为清理函数使用的闭包。

[Python 官方文档](https://docs.python.org/3/library/contextlib.html#contextlib.AsyncExitStack)说明，`AsyncExitStack` 可以组合多个同步或异步清理操作，并在关闭时反向执行回调。这和可逆效应账本非常接近。

### 2.3 空间可组合性：我依赖谁，依赖变化怎么办

空间可组合性关注组件之间的关系。

假设 `HeartbeatPlugin` 依赖 `ClockService`：

```text
ClockService 不存在  -> HeartbeatPlugin 保持未激活
ClockService 出现    -> HeartbeatPlugin 启动
ClockService 要退出  -> 先停止 HeartbeatPlugin
HeartbeatPlugin 停止 -> ClockService 才能安全退出
```

普通依赖注入只回答“启动时把哪个对象传进来”。响应式依赖还要回答“运行中这个对象离开了怎么办”。因此，一个真正的动态插件运行时还需要：

- 依赖声明；
- 服务注册表；
- 提供者解析；
- 依赖图；
- 生命周期协调器；
- 依赖变化后的重新协调。

### 2.4 Context 不是聊天上下文

文章中的 `Context` 不是 LLM 的历史消息，也不等于 Python 的 `contextvars.Context`。

可以先把它理解为三个东西的组合：

```text
Context = 当前可见服务 + 依赖解析视图 + 本组件的清理账本
```

插件只通过自己的 Context 做受控操作，运行时才能知道：

- 这个服务是谁注册的；
- 这个任务属于哪个插件；
- 卸载插件时要执行哪些清理；
- 哪些消费者依赖这个服务；
- 某个子树应该看到哪个服务实现。

如果插件直接修改全局字典、偷偷启动线程或把资源藏到全局变量里，Context 就无法追踪它，可逆保证也会失效。

### 2.5 Fiber 是一次挂载记录

同一份插件代码可以被加载多次，每次的配置、依赖和资源都可能不同。Fiber 表示“一次具体挂载的运行时实例”，它不是插件源码本身。

教学版可以先用一个 `MountedPlugin` 数据类表达 Fiber 的一小部分：

```python
@dataclass
class MountedPlugin:
    plugin: Plugin
    context: PluginContext
    bindings: dict[str, str]
```

这里保存了本次挂载使用的插件、Context，以及每个依赖实际绑定到哪个提供者。

### 2.6 静止状态与路径无关

论文使用 `quiescent state` 表示生命周期协调完成后，所有组件都到达目标状态。可以把它理解为“该启动的都启动了，该停止的都停止了，系统暂时安静下来”。

[论文第 4.6 节的汇合结论](https://github.com/cordiverse/paper/blob/main/paper.pdf)不是无条件的。它要求组件效应相互独立、组件完整提供自己声明的能力、依赖关系满足相应条件、最终状态没有失败的 Fiber 等。在这些前提下，运行时经过多次加载、卸载和替换后，静止状态可以与直接从最终配置装配得到的状态观察等价。

因此，更准确的说法是：

> 在论文给定前提内，最终静止状态主要由最终组合决定，而不是由中间变更路径决定。

不能把它简化成“任何 Python 代码都能百分之百回到原样”。

### 2.7 观察等价和系统边界

释放内存后，堆布局未必逐字节回到 `malloc` 之前；关闭再重新打开端口，底层对象也不是原来的对象。只要系统允许的观察者无法区分清理后的状态和原状态，就可以认为它们观察等价。

[论文第 6.1 节](https://github.com/cordiverse/paper/blob/main/paper.pdf)把外部操作拆成两部分：

- 获取资源：例如 `open` 得到文件描述符，`malloc` 得到内存，启动子进程得到进程句柄。这些句柄通常可以登记和释放。
- 向外发送：例如写入共享文件、发出网络数据、发送消息或完成扣款。数据一旦离开系统边界，通常不能靠关闭句柄撤销。

对外部影响常见的工程策略有：

1. 延迟提交，确认内部状态稳定后再向外发送。
2. 幂等键，重复执行时外部系统只接受一次。
3. 补偿操作，例如退款、发送撤回请求、删除刚创建的远程对象。
4. 事件日志和审计记录，知道做过什么、补偿是否成功。

补偿不是时间倒流。退款和“从未扣款”在某些业务观察下可以等价，但审计日志、通知和资金占用时间仍然不同。

## 3. 如果用 Python 做，需要哪些技术

### 3.1 技术映射总表

| 框架问题 | Python 技术 | 用途 | 初学阶段是否必需 |
| --- | --- | --- | --- |
| 定义插件契约 | `typing.Protocol` | 约定插件需要哪些属性和方法，保留鸭子类型 | 必需 |
| 保存运行时记录 | `dataclasses.dataclass` | 表达服务条目、挂载实例和配置 | 必需 |
| 管理服务 | `dict`、`set` | 按名称查找服务、保存依赖和已挂载插件 | 必需 |
| 记录清理动作 | 闭包、`Callable` | 动作执行时捕获相应的撤销逻辑 | 必需 |
| 反向清理 | `contextlib.AsyncExitStack` | 统一登记同步和异步清理，关闭时执行 LIFO | 必需 |
| 异步 I/O | `asyncio`、`async`、`await` | 等待模型、网络、子进程和流式数据 | Agent 场景必需 |
| 后台任务 | `asyncio.Task` | 运行心跳、流读取、队列消费者等长生命周期任务 | 常用 |
| 结构化并发 | `asyncio.TaskGroup` | 让一组子任务共享清晰的父生命周期和错误传播 | 进阶必需 |
| 取消任务 | `Task.cancel()`、`CancelledError` | 插件退出时停止后台任务并等待其清理 | 必需 |
| 依赖解析 | 拓扑排序或固定点计算 | 判断哪些插件当前可以启动 | 必需 |
| 响应依赖变化 | Reconciler 协调循环 | 比较期望配置和当前状态，执行启动与停止 | 必需 |
| 动态加载代码 | `importlib`、入口点 `entry_points` | 从配置或安装包发现插件 | 第二阶段 |
| 配置校验 | PyYAML、Pydantic | 把 YAML 转成经过校验的配置对象 | 第二阶段 |
| 事件系统 | `asyncio.Queue`、发布订阅 | 解耦服务之间的通知和流式事件 | 第二阶段 |
| 测试异步生命周期 | pytest、pytest-asyncio | 验证失败回滚、取消、依赖顺序和资源泄漏 | 必需 |
| 文件热更新 | watchfiles | 监听代码或配置变化，触发重新协调 | 后期能力 |
| 可观测性 | `logging`、结构化事件 | 追踪谁注册、谁依赖、为何启动或停止 | 生产化必需 |

当前 `mewcode-python` 已要求 Python 3.11 以上，并已经依赖 PyYAML、Pydantic、pytest 和 pytest-asyncio，因此做教学版不需要先更换项目技术栈。

### 3.2 `async` 到底解决什么

先看最小例子：

```python
import asyncio

async def fetch_model_reply() -> str:
    await asyncio.sleep(0.1)  # 模拟等待网络响应
    return "模型回复"

async def main() -> None:
    reply = await fetch_model_reply()
    print(reply)

asyncio.run(main())
```

几个关键词可以这样理解：

- `async def`：调用后得到协程对象，不会像普通函数那样立刻跑完整个函数。
- `await`：当前协程在这里等待，并把执行机会交回事件循环。
- 事件循环：在多个可继续运行的任务之间调度。
- `Task`：已经交给事件循环调度的协程。
- 并发：多个任务在等待期间交错推进，不等于多核并行。

只有写两个协程并顺序 `await`，仍然是顺序执行。需要并发时，可以使用 `TaskGroup`：

```python
async with asyncio.TaskGroup() as group:
    group.create_task(read_model_stream())
    group.create_task(read_tool_output())
```

[Python 官方文档](https://docs.python.org/3/library/asyncio-task.html#task-groups)说明，`TaskGroup` 退出时会等待内部任务；其中一个任务以普通异常失败时，其余任务会被取消，错误最终以异常组传播。这比到处创建无人管理的后台任务更安全。

### 3.3 为什么插件退出必须理解取消

调用 `task.cancel()` 不是立刻杀死代码。它会在任务下一次获得执行机会时抛出 `asyncio.CancelledError`。

因此，长任务需要在 `finally` 中清理自己的局部资源：

```python
async def worker() -> None:
    try:
        while True:
            await do_one_job()
    finally:
        await close_connection()
```

如果显式捕获 `CancelledError`，清理后通常要继续抛出。[Python 官方文档](https://docs.python.org/3/library/asyncio-task.html#task-cancellation)特别提醒，不应随意吞掉这个异常，否则 `TaskGroup`、超时和结构化并发可能行为异常。

### 3.4 为什么 `AsyncExitStack` 很适合做 Effect 账本

```python
from contextlib import AsyncExitStack

stack = AsyncExitStack()
await stack.__aenter__()

stack.callback(unregister_tool, "search")
stack.push_async_callback(close_database)
stack.push_async_callback(stop_worker)

await stack.aclose()
```

关闭时的执行顺序是：

```text
stop_worker -> close_database -> unregister_tool
```

它还有一个重要优点：如果插件启动到一半失败，已经登记的清理动作仍然可以执行，不需要等到完整的 `stop()` 方法准备好。

### 3.5 `Protocol` 为什么比强制继承更适合插件契约

```python
from typing import Protocol

class Plugin(Protocol):
    name: str
    requires: frozenset[str]
    provides: frozenset[str]

    async def start(self, ctx: "PluginContext") -> None:
        ...
```

实现类不必继承 `Plugin`，只要结构满足协议，静态类型检查器就可以接受。这叫结构化子类型，也可以理解为“带类型提示的鸭子类型”。

注意，`Protocol` 主要帮助静态检查，它不会自动验证业务语义。例如，插件写了 `provides = {"clock"}` 却没有真正注册服务，仍然需要运行时检查。

### 3.6 `contextvars` 要不要用

`contextvars` 适合保存“当前请求 ID”“当前 Agent ID”这类随异步任务传播的局部状态。它不是插件服务注册表，也不会自动管理插件依赖和清理。

可以在后期这样使用：

```python
from contextvars import ContextVar

current_plugin = ContextVar[str]("current_plugin")
```

日志函数就能知道当前代码属于哪个插件。但核心 Context 仍然应该是显式的运行时对象，不能用 `ContextVar` 代替依赖图和 Effect 账本。

## 4. 可运行 Demo：一个最小异步插件运行时

### 4.1 Demo 要证明什么

这个 Demo 不连接大模型，也不做动态 `import`。它只验证最核心的四件事：

1. `ClockPlugin` 提供 `clock` 服务。
2. `HeartbeatPlugin` 声明依赖 `clock`，依赖满足后才启动后台任务。
3. 配置中移除提供者时，运行时先取消消费者任务，再移除服务。
4. `BrokenPlugin` 启动到一半报错时，已经注册的临时服务会自动回滚。

运行要求是 Python 3.11 以上，只使用标准库。

<!-- demo:start -->
```python
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Coroutine, Protocol


class Plugin(Protocol):
    """插件只描述契约，不强制具体实现继承某个基类。"""

    name: str
    requires: frozenset[str]
    provides: frozenset[str]

    async def start(self, ctx: "PluginContext") -> None:
        """启动插件，并通过 ctx 登记服务、任务和清理动作。"""


@dataclass(slots=True)
class ServiceEntry:
    owner: str
    value: Any


@dataclass(slots=True)
class MountedPlugin:
    plugin: Plugin
    context: "PluginContext"
    bindings: dict[str, str]


class PluginContext:
    """每次插件挂载都有自己的 Context 和 Effect 清理栈。"""

    def __init__(self, runtime: "Runtime", plugin: Plugin) -> None:
        self._runtime = runtime
        self._plugin = plugin
        self._stack = AsyncExitStack()

    async def open(self) -> None:
        await self._stack.__aenter__()

    async def close(self) -> None:
        await self._stack.aclose()

    def require(self, key: str) -> Any:
        """读取插件已经声明的依赖。"""
        if key not in self._plugin.requires:
            raise RuntimeError(
                f"{self._plugin.name} 读取了未声明的依赖 {key!r}"
            )
        try:
            return self._runtime.services[key].value
        except KeyError as exc:
            raise RuntimeError(f"服务 {key!r} 当前不可用") from exc

    def provide(self, key: str, value: Any) -> None:
        """注册服务，并立刻把反向的注销动作记入 Effect 栈。"""
        if key not in self._plugin.provides:
            raise RuntimeError(
                f"{self._plugin.name} 注册了未声明的服务 {key!r}"
            )
        if key in self._runtime.services:
            owner = self._runtime.services[key].owner
            raise RuntimeError(f"服务 {key!r} 已由 {owner} 提供")

        self._runtime.services[key] = ServiceEntry(
            owner=self._plugin.name,
            value=value,
        )
        print(f"[provide] {self._plugin.name} -> {key}")

        async def undo_service() -> None:
            current = self._runtime.services.get(key)
            if current is not None and current.owner == self._plugin.name:
                del self._runtime.services[key]
                print(f"[dispose] {self._plugin.name} -/-> {key}")

        self._stack.push_async_callback(undo_service)

    def spawn(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        """创建属于当前插件的任务，并登记取消和等待逻辑。"""
        task = asyncio.create_task(coroutine, name=name)

        async def stop_task() -> None:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                print(f"[task stopped] {task.get_name()}")

        self._stack.push_async_callback(stop_task)
        return task


class Runtime:
    """负责服务注册、依赖解析、挂载、卸载和重新协调。"""

    def __init__(self, plugins: list[Plugin]) -> None:
        self.catalog = {plugin.name: plugin for plugin in plugins}
        if len(self.catalog) != len(plugins):
            raise ValueError("插件名称不能重复")

        self.services: dict[str, ServiceEntry] = {}
        self.mounted: dict[str, MountedPlugin] = {}
        self.mount_order: list[str] = []

    def _target_plan(
        self,
        desired: set[str],
    ) -> tuple[list[str], dict[str, dict[str, str]], set[str]]:
        """计算当前配置下可以激活的插件及其依赖绑定。"""
        unknown = desired - self.catalog.keys()
        if unknown:
            raise KeyError(f"未知插件：{sorted(unknown)}")

        declared_provider: dict[str, str] = {}
        for plugin_name in sorted(desired):
            for key in self.catalog[plugin_name].provides:
                old_owner = declared_provider.get(key)
                if old_owner is not None:
                    raise RuntimeError(
                        f"服务 {key!r} 同时由 {old_owner} 和 {plugin_name} 声明"
                    )
                declared_provider[key] = plugin_name

        remaining = set(desired)
        available: dict[str, str] = {}
        order: list[str] = []
        bindings: dict[str, dict[str, str]] = {}

        while remaining:
            ready = sorted(
                name
                for name in remaining
                if self.catalog[name].requires <= available.keys()
            )
            if not ready:
                break

            for name in ready:
                plugin = self.catalog[name]
                bindings[name] = {
                    key: available[key]
                    for key in plugin.requires
                }
                order.append(name)
                remaining.remove(name)
                for key in plugin.provides:
                    available[key] = name

        return order, bindings, remaining

    async def reconcile(self, desired: set[str]) -> None:
        """让当前运行状态逐步收敛到 desired 所描述的状态。"""
        target_order, target_bindings, inactive = self._target_plan(desired)
        target = set(target_order)

        must_stop = {
            name
            for name, mounted in self.mounted.items()
            if name not in target
            or mounted.bindings != target_bindings[name]
        }

        # 反向挂载顺序保证消费者先于提供者停止。
        for name in reversed(self.mount_order.copy()):
            if name in must_stop:
                await self._unmount(name)

        # 正向依赖顺序保证提供者先于消费者启动。
        for name in target_order:
            if name not in self.mounted:
                await self._mount(name, target_bindings[name])

        if inactive:
            print(f"[inactive] 依赖未满足或存在环：{sorted(inactive)}")

    async def _mount(self, name: str, bindings: dict[str, str]) -> None:
        plugin = self.catalog[name]
        context = PluginContext(self, plugin)
        await context.open()

        try:
            await plugin.start(context)
            actual = {
                key
                for key, entry in self.services.items()
                if entry.owner == name
            }
            missing = plugin.provides - actual
            if missing:
                raise RuntimeError(
                    f"{name} 没有注册已声明的服务：{sorted(missing)}"
                )
        except BaseException:
            # 即使 start() 只执行了一半，也回收已经登记的 Effect。
            await context.close()
            raise

        self.mounted[name] = MountedPlugin(
            plugin=plugin,
            context=context,
            bindings=bindings,
        )
        self.mount_order.append(name)
        print(f"[mounted] {name}")

    async def _unmount(self, name: str) -> None:
        mounted = self.mounted.pop(name)
        self.mount_order.remove(name)
        print(f"[unmounting] {name}")
        await mounted.context.close()
        print(f"[unmounted] {name}")

    async def close(self) -> None:
        await self.reconcile(set())


class ClockPlugin:
    name = "clock"
    requires = frozenset()
    provides = frozenset({"clock"})

    async def start(self, ctx: PluginContext) -> None:
        loop = asyncio.get_running_loop()
        ctx.provide("clock", lambda: round(loop.time(), 3))


class HeartbeatPlugin:
    name = "heartbeat"
    requires = frozenset({"clock"})
    provides = frozenset()

    async def start(self, ctx: PluginContext) -> None:
        clock = ctx.require("clock")

        async def worker() -> None:
            try:
                while True:
                    print(f"[heartbeat] {clock()}")
                    await asyncio.sleep(0.03)
            finally:
                print("[heartbeat] worker finally")

        ctx.spawn(worker(), name="heartbeat-worker")


class BrokenPlugin:
    name = "broken"
    requires = frozenset()
    provides = frozenset({"temporary"})

    async def start(self, ctx: PluginContext) -> None:
        ctx.provide("temporary", object())
        raise RuntimeError("模拟插件启动失败")


async def main() -> None:
    runtime = Runtime([ClockPlugin(), HeartbeatPlugin()])
    try:
        print("\n== 启动提供者和消费者 ==")
        await runtime.reconcile({"clock", "heartbeat"})
        await asyncio.sleep(0.08)

        print("\n== 配置只保留消费者，依赖不满足 ==")
        await runtime.reconcile({"heartbeat"})
        assert runtime.services == {}
        assert runtime.mounted == {}

        print("\n== 恢复提供者和消费者 ==")
        await runtime.reconcile({"clock", "heartbeat"})
        await asyncio.sleep(0.05)
    finally:
        await runtime.close()

    print("\n== 验证启动失败回滚 ==")
    broken_runtime = Runtime([BrokenPlugin()])
    try:
        await broken_runtime.reconcile({"broken"})
    except RuntimeError as exc:
        print(f"[expected error] {exc}")
    finally:
        await broken_runtime.close()

    assert broken_runtime.services == {}
    print("[ok] 临时服务没有泄漏")


if __name__ == "__main__":
    asyncio.run(main())
```
<!-- demo:end -->

### 4.2 运行方式和预期现象

把代码保存成 `cordis_runtime_demo.py` 后运行：

```bash
uv run python cordis_runtime_demo.py
```

具体时间数字和心跳次数可能不同，但顺序应该包含：

```text
[provide] clock -> clock
[mounted] clock
[mounted] heartbeat
[heartbeat] ...
[unmounting] heartbeat
[heartbeat] worker finally
[task stopped] heartbeat-worker
[unmounted] heartbeat
[unmounting] clock
[dispose] clock -/-> clock
[unmounted] clock
[inactive] 依赖未满足或存在环：['heartbeat']
...
[dispose] broken -/-> temporary
[expected error] 模拟插件启动失败
[ok] 临时服务没有泄漏
```

关键观察点有两个：

- `heartbeat` 总是在 `clock` 之前卸载，因为消费者要先退出。
- `BrokenPlugin.start()` 虽然没有正常结束，`temporary` 服务仍被清理，因为注册服务时已经立即登记了反向动作。

## 5. Demo 模块逐个解释

### 5.1 `Plugin`：契约

`Plugin` 只规定四件事：

- 插件名称；
- 需要的服务；
- 提供的服务；
- 启动入口。

它没有单独要求 `stop()`。清理逻辑在资源创建时就登记到 Context，避免“启动做了十件事，停止时漏写两件事”。

### 5.2 `ServiceEntry`：服务与所有者

服务表不能只存 `key -> value`，还要保存所有者：

```text
clock -> ServiceEntry(owner="clock", value=<function>)
```

这样卸载时才能确认当前服务确实属于这个插件，避免旧插件错误删除新提供者刚注册的同名服务。

### 5.3 `MountedPlugin`：教学版 Fiber

它记录一次挂载实例的：

- 插件对象；
- 专属 Context；
- 实际依赖绑定。

保存 `bindings` 很重要。如果 `clock` 服务从提供者 A 切换到提供者 B，即使消费者名称和配置不变，也需要判断消费者是否应重新激活。

### 5.4 `PluginContext`：受控操作入口

它主要提供三个能力：

- `require()`：只允许读取已经声明的依赖；
- `provide()`：注册服务并登记注销动作；
- `spawn()`：创建后台任务并登记取消、等待动作。

Context 的价值来自约束。所有共享影响都走这里，运行时才有机会追踪和清理。

### 5.5 `AsyncExitStack`：Effect 累加器

每次调用 `provide()` 或 `spawn()`，都会向清理栈压入一个回调。

```text
先 provide，后 spawn
关闭时先 stop task，后 remove service
```

Demo 中消费者和提供者属于两个不同 Context。单个 Context 内由 `AsyncExitStack` 反向清理，多个插件之间由 Runtime 按反向挂载顺序清理。

### 5.6 `_target_plan()`：依赖固定点

这个函数反复寻找“依赖已经满足”的插件：

```text
第 1 轮：clock 不依赖任何服务，可以激活
可用服务：clock

第 2 轮：heartbeat 依赖 clock，现在可以激活
```

如果一轮之后没有新插件可以激活，剩余插件可能缺少提供者，也可能形成依赖环。生产版应该给出更精确的诊断，Demo 为了聚焦只统一标成未激活。

### 5.7 `reconcile()`：期望状态与当前状态的协调器

它接收完整期望集合，而非“请启动某插件”这种命令：

```python
await runtime.reconcile({"clock", "heartbeat"})
```

协调过程是：

```mermaid
flowchart LR
    A["读取期望插件集合"] --> B["解析依赖与目标绑定"]
    B --> C["反向停止多余或绑定变化的插件"]
    C --> D["正向启动当前可激活的插件"]
    D --> E["报告未满足依赖或依赖环"]
```

这种接口比连续执行“加载 A、卸载 B、重启 C”更接近声明式系统。调用者说明“我要什么”，Runtime 计算“从现在怎么走过去”。

### 5.8 `_mount()`：失败安全启动

`_mount()` 先打开 Context，再调用插件的 `start()`。任何步骤失败都会关闭 Context，清理已经创建的资源。

捕获的是 `BaseException`，因为取消异常也必须触发清理，然后继续向上传播。这里不是吞掉异常，只是在异常离开前确保资源被回收。

### 5.9 `_unmount()`：生命周期顺序

Runtime 保存挂载顺序，卸载时反向遍历。由于依赖解析保证提供者先启动、消费者后启动，反向顺序自然就是消费者先退出、提供者后退出。

复杂生产系统不能只依靠一个全局列表，还要处理多个提供者、隔离域、并行停止、正在执行的请求和超时。但这个列表足以展示基本原理。

### 5.10 三个示例插件

- `ClockPlugin` 展示服务提供和自动注销。
- `HeartbeatPlugin` 展示服务依赖、后台任务、取消和 `finally`。
- `BrokenPlugin` 展示部分启动失败时的回滚。

这三个例子没有大模型，反而更适合学习框架，因为输出确定，错误边界也容易观察。

## 6. Demo 没有实现什么

这个 Demo 是概念验证，不是 Cordis 的 Python 等价实现。它没有：

- 多个同类服务提供者和服务 Broker；
- 插件配置更新和增量重载；
- 子 Context、服务隔离和拦截；
- 动态模块导入、模块缓存失效和事务式热更新；
- 事件系统和中间件；
- 跨进程调用和沙箱；
- 正在执行请求的排空；
- 超时、强制终止和僵尸任务检测；
- 持久化会话、事件回放和审计日志；
- 外部副作用的幂等与补偿；
- 论文完整的 Fiber 状态机和形式化保证。

尤其要注意，Python 的 `importlib.reload()` 只会重新执行模块代码。已经被其他模块持有的旧对象、旧类实例和后台任务不会自动消失，所以“动态导入”不等于“安全热重载”。

## 7. 推荐的分阶段学习路线

### 阶段 1：同步资源清理

先不用 `asyncio`，只练习：

- 函数返回清理函数；
- `try/finally`；
- `with` 和上下文管理器；
- `ExitStack`；
- LIFO 顺序。

目标是能解释为什么“创建资源时立即登记清理”比最后统一写 `stop()` 更可靠。

### 阶段 2：契约、注册表和依赖注入

学习：

- `Protocol`；
- `dataclass`；
- 字典注册表；
- Definition、Provider、Consumer；
- Composition Root。

仓库已有的[《Mini Plugin Agent：面向 Python 新手的插件化编程学习设计》](./plugin-agent-learning-design.md)对这一阶段有更完整的概念说明。

### 阶段 3：`asyncio` 生命周期

学习：

- 协程和 Task；
- `await` 的让出执行权；
- 任务取消；
- `CancelledError`；
- 异步上下文管理器；
- `AsyncExitStack`；
- `TaskGroup`。

目标是插件退出后没有仍在运行的任务，也没有“Task exception was never retrieved”。

### 阶段 4：依赖协调器

在 Demo 上增加：

- 明确区分缺失依赖和依赖环；
- 同名服务冲突诊断；
- 提供者替换后只重启受影响的消费者；
- 可选依赖；
- 配置 Diff；
- 生命周期事件日志。

### 阶段 5：配置和动态发现

再加入：

- YAML 配置；
- Pydantic 校验；
- `importlib` 或 Python 包入口点；
- 插件版本和接口兼容性；
- 文件监听。

自动扫描和热更新可以放到后面。加载代码相对简单，安全卸载和失败恢复更难。

### 阶段 6：Agent 能力

最后接入：

- LLM Provider；
- Tool Registry；
- Session Store；
- Agent Loop；
- 流式事件；
- 子进程和沙箱；
- 审批和权限；
- 外部操作的幂等与补偿。

这样可以始终分清“插件运行时问题”和“Agent 产品问题”。

## 8. 建议练习

1. 给 Demo 增加 `LoggerPlugin`，让 `HeartbeatPlugin` 同时依赖 `clock` 和 `logger`。
2. 构造 A 依赖 B、B 依赖 A 的环，输出完整环路径，而不是笼统提示。
3. 增加第二个 Clock Provider，设计显式优先级，切换时只重启相关消费者。
4. 给 `spawn()` 增加停止超时。超时后记录错误，但不要假装任务已经安全退出。
5. 增加 `ctx.on(event, handler)`，注册时自动登记取消监听。
6. 用 pytest-asyncio 验证启动失败后服务表为空。
7. 用一个假的远程支付服务练习幂等键和退款补偿，并写清楚为什么退款不等于真正回滚。
8. 为每个 Effect 生成编号，输出“由谁创建、何时清理、清理是否成功”。

## 9. 常见误区

### 误区 1：用了 `async` 就自动并发

`async def` 只创建协程函数。只有协程被 `await` 或包装成 Task，并由事件循环调度，代码才会执行。顺序 `await` 仍然可能是顺序运行。

### 误区 2：取消任务等于立即终止

取消通过异常协作完成。任务如果长时间不 `await`、执行阻塞代码或错误吞掉取消异常，可能无法及时退出。

### 误区 3：垃圾回收会替我清理

垃圾回收不等于资源生命周期。数据库事务、文件、网络连接、子进程和事件监听都应该显式清理，不能依赖 `__del__` 的执行时机。

### 误区 4：所有副作用都能撤销

只有系统能追踪并控制的影响才能可靠清理。已经到达外部世界的数据通常需要补偿，而不是普通的反向回调。

### 误区 5：Context 就是一个全局字典

字典只解决存取。真正的 Context 还要表达作用域、所有者、依赖解析、生命周期和隔离。

### 误区 6：动态导入就是热重载

热重载需要配置 Diff、模块失效、旧实例卸载、失败回退和状态协调。`importlib.import_module()` 只解决其中很小的一步。

### 误区 7：运行时可以修复任意插件

插件仍然可以绕开 Context 修改全局状态。要获得更强保证，需要静态检查、受限 API、进程边界或沙箱。

## 10. 读完后应该能回答的问题

1. 时间可组合性和空间可组合性分别解决什么问题？
2. 为什么清理动作要按 LIFO 执行？
3. 为什么 `asyncio` 很重要，却不等于可逆性？
4. `Task.cancel()` 之后为什么还要 `await task`？
5. `AsyncExitStack` 如何处理插件只启动一半就失败？
6. 为什么消费者必须先于提供者停止？
7. Cordis Context、LLM 上下文和 `contextvars` 有什么区别？
8. 为什么“观察等价”比“物理状态完全相同”更现实？
9. 为什么退款是补偿，而不是真正回滚？
10. 为什么动态 `import` 不是热重载？

如果这些问题能不用背术语、用自己的例子解释清楚，就已经掌握了这篇文章最重要的框架思想和一组很实用的 Python 基础。

## 11. 一手资料与延伸阅读

1. [知乎原文：段小草的回答](https://www.zhihu.com/question/2071375581464343126/answer/2071477434554249696)
2. [论文仓库：A Programming Paradigm for Spatiotemporal Composability](https://github.com/cordiverse/paper)，当前 README 标记为 2026-08-13 预印本并提示仍在修订
3. [DeepSeek Harness 官方仓库](https://github.com/deepseek-ai/deepseek-harness)
4. [DeepSeek Harness 架构说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)
5. [Cordis Primer](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-primer.md)
6. [Koishi：可逆的插件系统](https://koishi.chat/zh-CN/cookbook/design/disposable.html)
7. [Python `contextlib` 官方文档](https://docs.python.org/3/library/contextlib.html)
8. [Python `asyncio` 协程与任务官方文档](https://docs.python.org/3/library/asyncio-task.html)
9. [Python `typing.Protocol` 官方文档](https://docs.python.org/3/library/typing.html#typing.Protocol)
