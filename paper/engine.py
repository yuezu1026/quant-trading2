"""
模拟交易引擎

实时行情驱动的虚拟交易。
核心逻辑复用回测引擎，但数据源切换为实时行情。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Optional, Callable

from core.types import (
    Bar, Tick, Order, OrderType, OrderStatus,
    Event, EventType, Account, Signal,
)
from core.event_bus import EventBus
from data import DataProvider, TradingCalendar
from strategy.base import StrategyWrapper
from risk.manager import RiskManager
from .account import PaperAccount

logger = logging.getLogger(__name__)


class PaperEngine:
    """
    模拟交易引擎。

    使用方式:
        engine = PaperEngine(strategy=wrapper, data_provider=provider)
        engine.start()
        # ... 策略自动根据实时行情产生信号并模拟成交 ...
        engine.stop()
    """

    def __init__(
        self,
        strategy: StrategyWrapper,
        data_provider: DataProvider,
        initial_cash: float = 100_000.0,
        risk_manager: Optional[RiskManager] = None,
    ):
        self._strategy = strategy
        self._data_provider = data_provider
        self._account = PaperAccount(initial_cash)
        self._event_bus = EventBus()
        self._risk = risk_manager or RiskManager()
        self._calendar = TradingCalendar()

        self._is_running = False
        self._current_prices: dict[str, float] = {}
        self._subscribed_codes: list[str] = []

        # 注册事件
        self._event_bus.register(EventType.SIGNAL, self._on_signal)
        self._event_bus.register(EventType.BAR, self._on_bar)
        self._event_bus.register(EventType.FILL, self._on_fill)

        # 回调
        self._on_update: Optional[Callable[[Account], None]] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, codes: list[str]) -> None:
        """启动模拟交易"""
        self._subscribed_codes = codes
        self._strategy.on_start()
        self._is_running = True
        logger.info(f"模拟交易启动: {codes}")

    def stop(self) -> None:
        """停止模拟交易"""
        self._is_running = False
        self._account.end_of_day()
        self._strategy.on_stop()
        logger.info("模拟交易停止")

    # ------------------------------------------------------------------
    # 行情处理
    # ------------------------------------------------------------------

    def on_tick(self, tick: Tick) -> list[Signal]:
        """
        处理逐笔数据。

        简化处理：将 tick 转为简化的 Bar 给策略。
        """
        if not self._is_running:
            return []

        self._current_prices[tick.code] = tick.price

        bar = Bar(
            code=tick.code,
            date=tick.datetime.date(),
            time=tick.datetime.strftime("%H:%M:%S"),
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
            amount=tick.price * tick.volume,
        )

        self._event_bus.emit(Event(type=EventType.BAR, data=bar))

        # 更新市值
        self._account.mark_to_market(self._current_prices)

        # 通知外部（WebSocket推送用）
        if self._on_update:
            self._on_update(self._account.account)

        return []

    def on_bar(self, bar: Bar) -> None:
        """处理K线数据（如分钟线）"""
        if not self._is_running:
            return

        self._current_prices[bar.code] = bar.close
        self._event_bus.emit(Event(type=EventType.BAR, data=bar))
        self._account.mark_to_market(self._current_prices)

        if self._on_update:
            self._on_update(self._account.account)

    def set_update_callback(self, cb: Callable[[Account], None]) -> None:
        """设置账户更新回调（供WebSocket推送）"""
        self._on_update = cb

    # ------------------------------------------------------------------
    # 手动交易
    # ------------------------------------------------------------------

    def place_order(
        self,
        code: str,
        side: str,
        quantity: int,
        price: Optional[float] = None,
    ) -> Order:
        """手动下单（Web API调用）"""
        from core.types import OrderSide, OrderType

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        exec_price = price or self._current_prices.get(code, 0.0)

        order = Order(
            order_id=f"ord_{uuid.uuid4().hex[:8]}",
            code=code,
            side=side_enum,
            quantity=quantity,
            price=exec_price,
            order_type=order_type,
            status=OrderStatus.PENDING,
        )

        self._account.submit_order(order)

        # 市价单立即尝试撮合
        if exec_price > 0:
            self._account.match_order(order, exec_price)

        return order

    def cancel_order(self, order_id: str) -> bool:
        return self._account.cancel_order(order_id)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_bar(self, event: Event) -> None:
        bar: Bar = event.data

        # 风控检查
        ok, reason = self._risk.check_all(
            [Signal(code="", side="buy", quantity=100)],  # placeholder
            self._account.account,
        )

        try:
            signals = self._strategy.on_bar(bar, self._account.account)
        except Exception:
            logger.exception(f"策略异常 @ {bar.code} {bar.date}")
            return

        for signal in signals:
            # 风控
            ok, reason = self._risk.check(signal, self._account.account)
            if not ok:
                logger.warning(f"风控拦截: {reason}")
                continue

            self._event_bus.emit(Event(type=EventType.SIGNAL, data=signal))

    def _on_signal(self, event: Event) -> None:
        signal: Signal = event.data

        order = Order(
            order_id=f"ord_{uuid.uuid4().hex[:8]}",
            code=signal.code,
            side=signal.side,
            quantity=signal.quantity,
            price=signal.price or self._current_prices.get(signal.code, 0.0),
            order_type=signal.order_type,
            status=OrderStatus.PENDING,
            signal=signal,
        )

        self._account.submit_order(order)

        # 尝试撮合
        cur_price = self._current_prices.get(signal.code, signal.price or 0)
        if cur_price > 0:
            self._account.match_order(order, cur_price)

    def _on_fill(self, event: Event) -> None:
        fill = event.data
        try:
            self._strategy.on_fill(fill, self._account.account)
        except Exception:
            logger.exception(f"策略 on_fill 异常")

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def account(self) -> Account:
        return self._account.account

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def positions(self) -> dict:
        return {
            code: {
                "quantity": p.quantity,
                "available": p.available,
                "avg_cost": p.avg_cost,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "unrealized_pnl": p.unrealized_pnl,
            }
            for code, p in self._account.account.positions.items()
            if p.quantity > 0
        }

    def get_dashboard_data(self) -> dict:
        """获取仪表盘数据"""
        acc = self._account.account
        return {
            "cash": acc.cash,
            "frozen_cash": acc.frozen_cash,
            "total_asset": acc.total_asset,
            "realized_pnl": acc.realized_pnl,
            "positions": self.positions,
            "is_running": self._is_running,
            "subscribed_codes": self._subscribed_codes,
        }
