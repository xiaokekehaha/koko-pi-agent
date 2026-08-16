# 咖啡店插件运行时：Cordis 设计哲学的 Python 教学原型

> PROTOTYPE：这是帮助理解设计的抛弃式代码，不是 Cordis 的 Python 移植，也不属于 MewCode 生产运行时。

运行：

```bash
uv run python -m examples.cordis_coffee_shop.demo
```

## 先看故事

咖啡店有三类能力：

```text
菜单服务 menu
├── 拿铁插件：往菜单注册表增加“拿铁”
└── 花茶插件：往菜单注册表增加“茉莉花茶”

支付服务 payment（同一时刻只能有一个 Provider）
├── 支付宝 Provider
└── 微信支付 Provider

收银台 checkout（Consumer）
└── inject = ("menu", "payment")
```

Demo 故意先挂载收银台。此时 `menu` 和 `payment` 都不存在，所以它只进入 `waiting`，不会启动。等两个服务都出现后，运行时根据 `inject` 自动启动收银台。

之后案例演示两种变化：

1. 拿铁下架、花茶上架：这里只改变 `menu` 内部的注册表，不替换 `menu` 服务，因此收银台不需要重启。
2. 支付宝替换成微信支付：这是替换独占的 `payment` 服务，因此运行时先停止收银台，再撤销支付宝，挂载微信支付，最后重新启动收银台。

## 代码与 Cordis 概念的对应关系

| 文章术语 | 案例代码 | 通俗解释 |
|---|---|---|
| Plugin | `MenuRuntimePlugin`、`DrinkPlugin` 等 | 一份“如何开店”的方案 |
| Fiber | `MountedPlugin` | 这份方案的一次具体开店记录 |
| Context | `PluginContext` | 本店能看到的服务和自己的清理账本 |
| Service | `menu`、`payment`、`checkout` | 通过稳定名称找到的共享能力 |
| Inject | `CheckoutPlugin.inject` | 开门前必须到齐的设施清单 |
| Effect | `PluginContext.effect()` | 做事时立即登记以后如何撤销 |
| 独占 Service | `payment` | 同一作用域只能有一个总收银渠道 |
| 注册表 Service | `Menu` | 多种饮品可以同时登记、分别撤销 |
| 热替换 | `Runtime.replace()` | 先关干净旧店，再按新方案开店 |

最关键的一行不是动态导入，而是：

```python
ctx.effect("下架拿铁", lambda: menu.register("拿铁", 28))
```

`menu.register()` 完成上架并返回“下架函数”；`effect()` 将它归到当前插件名下。插件卸载时，运行时按相反顺序调用清理函数。因此谁产生副作用，谁就拥有它的清理责任。

## Definition / Provider / Consumer

支付能力被分成三层：

```text
Definition: Payment Protocol
Provider:   AlipayPayment / WechatPayment
Consumer:   CheckoutPlugin
```

`CheckoutPlugin` 只认识 `Payment` 契约和服务名 `payment`，不引用支付宝或微信支付的具体类。替换 Provider 时，Consumer 的业务代码不需要修改。

## 与 DeepSeek Harness 源码的对应依据

文章固定使用 DeepSeek Harness commit `47f943859bef60e4160492346772ded9b24f765a` 和 `@deepseek-ai/cordis@4.0.1`。这个原型对应了其中四个直接可观察的机制：

- [`RegistryService.plugin()`](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/vendor/cordis/src/registry.ts#L316-L330) 创建 Fiber，但插件代码要等依赖就绪后才执行。
- [`Fiber`](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/vendor/cordis/src/fiber.ts#L222-L265) 保存一次挂载的 config、inject、子 Context 和生命周期状态。
- [`provide()`](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/vendor/cordis/src/reflect.ts#L277-L305) 本身通过 Fiber Effect 注册，卸载时先通知并等待依赖方停止，再撤销服务。
- [`tool-bash`](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/shell/tool-bash/src/index.ts#L31) 只声明需要 `shell`，而 [`ShellExecutor`](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/shell/shell/src/index.ts#L40-L68) 定义稳定契约；这对应案例里的 `CheckoutPlugin` 与 `Payment`。

原文：[《Cordis 在做什么：从 DeepSeek Harness 看》](https://blog.antinomie.org/)

## 刻意省略的部分

为了让一次运行就能看懂，本案例没有实现：

- Cordis 完整 Fiber 状态机；
- Context 父子树和级联所有权；
- `isolate` 服务解析空间；
- YAML Loader、patch 和 preset；
- 异步 Effect、失败回滚和并发；
- 动态模块导入或文件监听。

所以它演示的是设计原则，不应被当成生产插件框架。完整的 Python 异步推演见 [`docs/cordis-python-async-learning-guide.md`](../../docs/cordis-python-async-learning-guide.md)。
