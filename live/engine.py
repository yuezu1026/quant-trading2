"""
实盘交易引擎

集成了券商网关、订单管理、持仓管理、风控的完整实盘引擎。
策略通过 on_bar() 产生信号 → 风控拦截 → 下单 → 成交回调。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Callable

from core.types import (
    Bar, Tick, Order, OrderStatus,
    Event, EventType, Signal, Fill, Account, Position,
)
from core.event_bus import EventBus
from strategy.base import StrategyWrapper
from risk.manager import RiskManager
from .gateways.base import TradingGateway, GatewayCallback
from .order_manager import OrderManager
from .position_manager import PositionManager

logger = logging.getLogger(__name__)


class LiveEngine(GatewayCallback):
    """
    实盘交易引擎。

    数据流:
        行情(Tick/Bar) → 策略.on_bar() → Signal
        → RiskManager.check() → OrderManager.create_order()
        → Gateway.submit_order() → Gateway回调
        → OrderManager.update_status() → PositionManager.on_fill()
        → Strategy.on_fill()

    使用方式:
        engine = LiveEngine(strategy=wrapper, gateway=gateway)
        engine.start(codes=["600000.SH"])
        # ... 策略自动运行 ...
        engine.stop()
    """

    def __init__(
        self,
        strategy: StrategyWrapper,
        gateway: TradingGateway,
        risk_manager: Optional[RiskManager] = None,
    ):
        super().__init__()
        self._strategy = strategy
        self._gateway = gateway
        self._risk = risk_manager or RiskManager()
        self._event_bus = EventBus()
        self._order_mgr = OrderManager()
        self._pos_mgr = PositionManager()

        self._is_running = False
        self._subscribed_codes: list[str] = []

        # 设置网关回调
        self._gateway.set_callback(self)

        # 注册事件
        self._event_bus.register(EventType.SIGNAL, self._on_signal)
        self._event_bus.register(EventType.BAR, self._on_bar)

        # 外部通知（WebSocket推送等）
        self._on_account_update: Optional[Callable[[Account], None]] = None

        # 监控线程
        self._monitor_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, codes: list[str], connect_kwargs: dict | None = None) -> bool:
        """
        启动实盘交易。

        1. 连接券商
        2. 同步持仓
        3. 订阅行情
        4. 启动策略
        5. 启动监控线程
        """
        # 连接券商
        kwargs = connect_kwargs or {}
        if not self._gateway.connect(**kwargs):
            logger.error("券商连接失败")
            return False

        # 同步持仓（以券商为准）
        broker_positions = self._gateway.query_positions()
        broker_account = self._gateway.query_account()
        self._pos_mgr.reconcile(broker_positions)

        logger.info(
            f"持仓同步: {len(broker_positions)}只, "
            f"总资产 ¥{broker_account.total_asset:,.2f}"
        )

        # 订阅行情
        self._subscribed_codes = codes
        self._gateway.subscribe(codes)

        # 启动策略
        self._strategy.on_start()

        # 启动监控
        self._is_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        logger.info(f"实盘引擎启动: {codes}")
        return True

    def stop(self) -> None:
        """停止实盘交易"""
        self._is_running = False

        self._strategy.on_stop()
        self._pos_mgr.end_of_day()
        self._gateway.unsubscribe(self._subscribed_codes)
        self._gateway.disconnect()

        # 撤销所有未成交订单
        for order in self._order_mgr.get_pending_orders():
            self._gateway.cancel_order(order.order_id)
            self._order_mgr.update_status(order.order_id, OrderStatus.CANCELLED)

        logger.info("实盘引擎停止")

    # ------------------------------------------------------------------
    # 行情回调 (从 Gateway)
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        """K线完成 → 通知策略"""
        if not self._is_running:
            return
        self._event_bus.emit(Event(type=EventType.BAR, data=bar))
        self._pos_mgr.mark_to_market({bar.code: bar.close})

    def on_tick(self, tick: Tick) -> None:
        """Tick 行情 → 转成简化 Bar 给策略"""
        if not self._is_running:
            return

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
        self._pos_mgr.mark_to_market({tick.code: tick.price})

    # ------------------------------------------------------------------
    # 交易回调 (从 Gateway)
    # ------------------------------------------------------------------

    def on_order_update(self, order: Order) -> None:
        """券商订单状态变更"""
        self._order_mgr.update_status(
            order.order_id,
            order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
        )
        logger.debug(f"订单更新: {order.order_id} → {order.status.value}")

    def on_fill(self, fill: Fill) -> None:
        """券商成交回报"""
        logger.info(f"成交: {fill.code} {fill.side.value} {fill.quantity}股 @{fill.price:.2f}")

        self._order_mgr.record_fill(fill.order_id, fill)
        self._pos_mgr.on_fill(fill)

        # 通知策略
        account = self._build_account()
        try:
            self._strategy.on_fill(fill, account)
        except Exception:
            logger.exception("策略 on_fill 异常")

    def on_position_update(self, positions: list[Position]) -> None:
        """券商持仓更新 → 对账"""
        self._pos_mgr.reconcile(positions)

    def on_account_update(self, account: Account) -> None:
        """券商账户更新"""
        if self._on_account_update:
            self._on_account_update(account)

    def on_error(self, error: str) -> None:
        logger.error(f"券商错误: {error}")
        # 同时发送告警
        from web.ws import push_alert
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(push_alert(error, "critical"))
        except Exception:
            pass

    def on_disconnected(self) -> None:
        logger.warning("券商连接断开，尝试重连...")
        # 重连逻辑
        for i in range(3):
            time.sleep(5 * (i + 1))
            if self._gateway.reconnect():
                logger.info("重连成功")
                self._gateway.subscribe(self._subscribed_codes)
                return

        logger.critical("重连失败，停止引擎")
        self.stop()

    def on_reconnected(self) -> None:
        logger.info("券商重连成功")

    # ------------------------------------------------------------------
    # 手动交易接口 (Web API调用)
    # ------------------------------------------------------------------

    def place_order(
        self, code: str, side: str, quantity: int, price: float = 0.0
    ) -> tuple[bool, str, Optional[Order]]:
        """
        手动下单（带风控检查）。

        Returns:
            (success, message, order)
        """
        # 创建订单
        order = self._order_mgr.create_manual_order(code, side, quantity, price)

        # 简易风控（卖出时检查 T+1）
        if side == "sell":
            can, reason = self._pos_mgr.can_sell(code, quantity)
            if not can:
                return False, reason, order

        # 提交到券商
        order = self._gateway.submit_order(order)

        if order.status == OrderStatus.REJECTED:
            return False, "券商拒绝", order

        return True, "已提交", order

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        order = self._order_mgr.get_order(order_id)
        if order is None or order.is_finished:
            return False

        ok = self._gateway.cancel_order(order_id)
        if ok:
            self._order_mgr.update_status(order_id, OrderStatus.CANCELLED)
        return ok

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_bar(self, event: Event) -> None:
        """行情事件 → 策略 → 信号"""
        bar: Bar = event.data
        account = self._build_account()

        try:
            signals = self._strategy.on_bar(bar, account)
        except Exception:
            logger.exception(f"策略异常 @ {bar.code}")
            return

        for signal in signals:
            # 风控检查
            ok, reason = self._risk.check(signal, account)
            if not ok:
                logger.warning(f"风控拦截: {signal.code} — {reason}")
                continue
            self._event_bus.emit(Event(type=EventType.SIGNAL, data=signal))

    def _on_signal(self, event: Event) -> None:
        """信号 → 订单 → 券商"""
        signal: Signal = event.data

        order = self._order_mgr.create_order(signal)
        order = self._gateway.submit_order(order)

        if order.status == OrderStatus.REJECTED:
            logger.error(f"券商拒单: {order.order_id}")
        else:
            logger.info(f"下单成功: {order.order_id}")

    # ------------------------------------------------------------------
    # 监控线程
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """监控线程：定期检查超时、对账、心跳"""
        while self._is_running:
            time.sleep(30)

            try:
                # 1. 超时订单检测
                timeout = self._order_mgr.check_timeouts()
                for order in timeout:
                    self._gateway.cancel_order(order.order_id)
                    self._order_mgr.update_status(order.order_id, OrderStatus.CANCELLED)
                    logger.warning(f"超时撤销: {order.order_id}")

                # 2. 持仓对账
                try:
                    broker_positions = self._gateway.query_positions()
                    self._pos_mgr.reconcile(broker_positions)
                except Exception:
                    pass

                # 3. 订单状态同步
                for order in self._order_mgr.get_pending_orders():
                    try:
                        updated = self._gateway.query_order(order.order_id)
                        if updated and updated.status != order.status:
                            self._order_mgr.update_status(order.order_id, updated.status,
                                filled_quantity=updated.filled_quantity,
                                avg_fill_price=updated.avg_fill_price)
                    except Exception:
                        pass

            except Exception:
                logger.exception("监控循环异常")

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _build_account(self) -> Account:
        """从持仓管理器构建账户对象"""
        positions = self._pos_mgr.positions
        total_mv = sum(p.market_value for p in positions.values())

        # 查询券商获取最新现金
        try:
            acc = self._gateway.query_account()
            cash = acc.cash
        except Exception:
            cash = 0.0

        return Account(
            cash=cash,
            total_asset=cash + total_mv,
            positions=positions,
            realized_pnl=self._pos_mgr.total_realized_pnl,
        )

    def set_account_callback(self, cb: Callable[[Account], None]) -> None:
        """设置账户更新回调（WebSocket推送）"""
        self._on_account_update = cb

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def orders(self) -> list[Order]:
        return self._order_mgr.get_orders()

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
            for code, p in self._pos_mgr.positions.items()
            if p.quantity > 0
        }

    def get_dashboard_data(self) -> dict:
        """仪表盘数据"""
        account = self._build_account()
        return {
            "cash": account.cash,
            "frozen_cash": account.frozen_cash,
            "total_asset": account.total_asset,
            "realized_pnl": account.realized_pnl,
            "unrealized_pnl": self._pos_mgr.total_unrealized_pnl,
            "positions": self.positions,
            "orders": self._order_mgr.stats,
            "is_running": self._is_running,
            "subscribed_codes": self._subscribed_codes,
        }
