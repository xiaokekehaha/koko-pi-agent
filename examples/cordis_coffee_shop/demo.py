"""PROTOTYPE: 用咖啡店演示 Cordis 风格的插件组合与可逆生命周期。

运行：uv run python -m examples.cordis_coffee_shop.demo

它不是 Cordis 的 Python 移植，只保留文章中最适合入门的几个机制：

1. 插件用 ``inject`` 声明依赖，不依赖书写顺序。
2. 服务名是 Provider 和 Consumer 之间的稳定契约。
3. 每次插件挂载都有独立的 MountedPlugin（教学版 Fiber）。
4. 所有注册都通过 ``effect`` 同时登记清理函数。
5. 替换独占服务时，先停止消费者，再撤销旧 Provider。
6. 注册表里的普通条目可以增删，而不必重启消费者。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast


Cleanup = Callable[[], None]
EffectSetup = Callable[[], Cleanup]


class Plugin(Protocol):
    """插件契约：声明名字、依赖，以及依赖齐全后的启动逻辑。"""

    name: str
    inject: tuple[str, ...]

    def start(self, ctx: PluginContext) -> None: ...


class Payment(Protocol):
    """Definition：支付能力的稳定契约。"""

    name: str

    def pay(self, amount: int) -> str: ...


class Menu:
    """注册表式服务：多种饮品可以同时登记。"""

    def __init__(self) -> None:
        self._prices: dict[str, int] = {}

    def register(self, drink: str, price: int) -> Cleanup:
        if drink in self._prices:
            raise ValueError(f"饮品已存在：{drink}")
        self._prices[drink] = price
        print(f"    [菜单] 上架 {drink}，价格 {price} 元")

        def unregister() -> None:
            self._prices.pop(drink, None)
            print(f"    [菜单] 下架 {drink}")

        return unregister

    def price_of(self, drink: str) -> int:
        if drink not in self._prices:
            raise ValueError(f"菜单里没有：{drink}")
        return self._prices[drink]

    def items(self) -> dict[str, int]:
        return dict(self._prices)


class Checkout:
    """Consumer 使用 Menu 和 Payment，但不知道具体 Provider 类。"""

    def __init__(self, menu: Menu, payment: Payment) -> None:
        self._menu = menu
        self._payment = payment

    def order(self, drink: str) -> str:
        price = self._menu.price_of(drink)
        receipt = self._payment.pay(price)
        return f"制作 {drink}；{receipt}"


@dataclass(frozen=True)
class ServiceEntry:
    value: Any
    owner: str


@dataclass
class MountedPlugin:
    """教学版 Fiber：记录某个插件这一次挂载的状态。"""

    plugin: Plugin
    state: str = "waiting"
    context: PluginContext | None = None
    bindings: dict[str, str] = field(default_factory=dict)


class PluginContext:
    """插件只能通过自己的 Context 访问服务、登记 Effect。"""

    def __init__(self, runtime: Runtime, owner: str) -> None:
        self._runtime = runtime
        self._owner = owner
        self._effects: list[tuple[str, Cleanup]] = []

    def get(self, service_name: str) -> Any:
        return self._runtime.get(service_name)

    def effect(self, label: str, setup: EffectSetup) -> None:
        """立即产生副作用，并保存对应的撤销函数。"""

        cleanup = setup()
        self._effects.append((label, cleanup))

    def provide(self, service_name: str, value: Any) -> None:
        """发布服务本身也是一个可逆 Effect。"""

        self.effect(
            f"撤销服务 {service_name}",
            lambda: self._runtime._register_service(
                service_name, value, owner=self._owner
            ),
        )

    def dispose(self) -> None:
        """按 LIFO 顺序撤销本插件创建的所有 Effect。"""

        while self._effects:
            label, cleanup = self._effects.pop()
            print(f"    [effect:undo] {self._owner} -> {label}")
            cleanup()


class Runtime:
    """很小的依赖调度器；只用于观察状态变化。"""

    def __init__(self) -> None:
        self._services: dict[str, ServiceEntry] = {}
        self._mounted: dict[str, MountedPlugin] = {}

    def mount(self, plugin: Plugin) -> None:
        if plugin.name in self._mounted:
            raise ValueError(f"插件已挂载：{plugin.name}")
        self._mounted[plugin.name] = MountedPlugin(plugin)
        print(f"[mount] {plugin.name}，inject={plugin.inject or '无'}")
        self._reconcile()

    def unmount(self, plugin_name: str) -> None:
        if plugin_name not in self._mounted:
            raise KeyError(f"插件未挂载：{plugin_name}")

        print(f"[unmount] {plugin_name}")
        self._stop_dependents_of(plugin_name)
        mounted = self._mounted[plugin_name]
        self._deactivate(mounted)
        del self._mounted[plugin_name]
        self._reconcile()

    def replace(self, old_name: str, replacement: Plugin) -> None:
        print(f"[replace] {old_name} -> {replacement.name}")
        self.unmount(old_name)
        self.mount(replacement)

    def get(self, service_name: str) -> Any:
        try:
            return self._services[service_name].value
        except KeyError as exc:
            raise LookupError(f"服务尚未就绪：{service_name}") from exc

    def show_state(self, title: str) -> None:
        print(f"\n=== {title} ===")
        print("插件：")
        if not self._mounted:
            print("  （无）")
        for mounted in self._mounted.values():
            missing = [
                name
                for name in mounted.plugin.inject
                if name not in self._services
            ]
            detail = f"，缺少={missing}" if missing else ""
            print(f"  - {mounted.plugin.name}: {mounted.state}{detail}")

        print("服务：")
        if not self._services:
            print("  （无）")
        for name, entry in self._services.items():
            print(f"  - {name}: 由 {entry.owner} 提供")

        menu_entry = self._services.get("menu")
        if menu_entry is not None:
            menu = cast(Menu, menu_entry.value)
            print(f"菜单：{menu.items() or '（空）'}")

    def shutdown(self) -> None:
        print("[shutdown] 关闭整棵插件树")
        for plugin_name in tuple(self._mounted):
            if plugin_name not in self._mounted:
                continue
            self._stop_dependents_of(plugin_name)
            self._deactivate(self._mounted[plugin_name])
        self._mounted.clear()

    def _register_service(
        self, service_name: str, value: Any, *, owner: str
    ) -> Cleanup:
        if service_name in self._services:
            current_owner = self._services[service_name].owner
            raise ValueError(
                f"独占服务 {service_name!r} 已由 {current_owner} 提供"
            )
        self._services[service_name] = ServiceEntry(value, owner)
        print(f"    [service:+] {owner} 提供 {service_name}")

        def unregister() -> None:
            current = self._services.get(service_name)
            if current is not None and current.owner == owner:
                del self._services[service_name]
                print(f"    [service:-] {owner} 撤销 {service_name}")

        return unregister

    def _reconcile(self) -> None:
        """反复启动依赖已齐全的插件，直到状态稳定。"""

        while True:
            started_any = False
            for mounted in self._mounted.values():
                if mounted.state != "waiting":
                    continue
                if not all(name in self._services for name in mounted.plugin.inject):
                    continue
                self._activate(mounted)
                started_any = True
            if not started_any:
                return

    def _activate(self, mounted: MountedPlugin) -> None:
        plugin = mounted.plugin
        context = PluginContext(self, plugin.name)
        mounted.context = context
        mounted.bindings = {
            service_name: self._services[service_name].owner
            for service_name in plugin.inject
        }
        print(f"  [start] {plugin.name}，绑定={mounted.bindings or '无'}")
        try:
            plugin.start(context)
        except Exception:
            context.dispose()
            mounted.context = None
            mounted.bindings.clear()
            raise
        mounted.state = "active"

    def _stop_dependents_of(self, provider_name: str) -> None:
        for mounted in tuple(self._mounted.values()):
            if mounted.state != "active":
                continue
            if provider_name not in mounted.bindings.values():
                continue
            self._stop_dependents_of(mounted.plugin.name)
            self._deactivate(mounted)

    def _deactivate(self, mounted: MountedPlugin) -> None:
        if mounted.state != "active":
            return
        print(f"  [stop] {mounted.plugin.name}")
        assert mounted.context is not None
        mounted.context.dispose()
        mounted.context = None
        mounted.bindings.clear()
        mounted.state = "waiting"


class MenuRuntimePlugin:
    name = "menu-runtime"
    inject: tuple[str, ...] = ()

    def start(self, ctx: PluginContext) -> None:
        ctx.provide("menu", Menu())


class DrinkPlugin:
    inject = ("menu",)

    def __init__(self, name: str, drink: str, price: int) -> None:
        self.name = name
        self._drink = drink
        self._price = price

    def start(self, ctx: PluginContext) -> None:
        menu = cast(Menu, ctx.get("menu"))
        ctx.effect(
            f"下架 {self._drink}",
            lambda: menu.register(self._drink, self._price),
        )


class AlipayPayment:
    name = "支付宝"

    def pay(self, amount: int) -> str:
        return f"使用支付宝支付 {amount} 元"


class WechatPayment:
    name = "微信支付"

    def pay(self, amount: int) -> str:
        return f"使用微信支付 {amount} 元"


class PaymentPlugin:
    inject: tuple[str, ...] = ()

    def __init__(self, name: str, payment: Payment) -> None:
        self.name = name
        self._payment = payment

    def start(self, ctx: PluginContext) -> None:
        ctx.provide("payment", self._payment)


class CheckoutPlugin:
    name = "checkout"
    inject = ("menu", "payment")

    def start(self, ctx: PluginContext) -> None:
        menu = cast(Menu, ctx.get("menu"))
        payment = cast(Payment, ctx.get("payment"))
        print(f"    [收银台] 开门，当前支付方式：{payment.name}")

        def close_checkout() -> None:
            print("    [收银台] 关门")

        ctx.effect("关闭收银台", lambda: close_checkout)
        ctx.provide("checkout", Checkout(menu, payment))


def place_order(runtime: Runtime, drink: str) -> None:
    checkout = cast(Checkout, runtime.get("checkout"))
    print(f"[order] {checkout.order(drink)}")


def main() -> None:
    runtime = Runtime()

    # 故意先挂消费者，证明启动顺序由 inject 决定，而不是由代码顺序决定。
    runtime.mount(CheckoutPlugin())
    runtime.show_state("1. 收银台先到，但依赖未齐，所以等待")

    runtime.mount(DrinkPlugin("latte-plugin", "拿铁", 28))
    runtime.mount(MenuRuntimePlugin())
    runtime.show_state("2. 菜单服务出现，拿铁自动上架；收银台仍等支付服务")

    runtime.mount(PaymentPlugin("alipay-provider", AlipayPayment()))
    runtime.show_state("3. 支付服务出现，收银台自动启动")
    place_order(runtime, "拿铁")

    # 拿铁只是 menu 注册表的一项。下架它不会替换 menu 服务，收银台无需重启。
    runtime.unmount("latte-plugin")
    runtime.mount(DrinkPlugin("tea-plugin", "茉莉花茶", 18))
    runtime.show_state("4. 注册表内容变化，收银台保持运行")

    # payment 是独占服务。替换它会先停依赖方，再撤销旧服务，最后重启依赖方。
    runtime.replace(
        "alipay-provider",
        PaymentPlugin("wechat-provider", WechatPayment()),
    )
    runtime.show_state("5. 支付 Provider 已热替换，收银台绑定到新实现")
    place_order(runtime, "茉莉花茶")

    runtime.shutdown()
    runtime.show_state("6. 关闭后，插件、服务和菜单注册全部清空")


if __name__ == "__main__":
    main()
