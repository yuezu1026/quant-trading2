"""
虚拟账户

模拟交易的账户管理，逻辑与 SimulatedBroker 中的账户一致，
但是作为独立模块，方便模拟交易引擎直接使用。
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.types import (
    OrderSide, OrderStatus,
    Order, Fill, Position, Account,
)

logger = logging.getLogger(__name__)

COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.001


class PaperAccount:
    """
    虚拟账户 — 模拟真实资金和持仓管理。

    与实盘账户接口一致，方便将来切换。
    """

    def __init__(self, initial_cash: float = 100_000.0):
        self._initial_cash = initial_cash
        self._account = Account(cash=initial_cash, total_asset=initial_cash)

        self._pending_orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._today_buy: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def account(self) -> Account:
        return self._account

    @property
    def cash(self) -> float:
        return self._account.cash

    @property
    def total_asset(self) -> float:
        return self._account.total_asset

    # ------------------------------------------------------------------
    # 订单管理
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        """提交订单，检查资金/持仓"""
        check = self._check_order(order)
        if check:
            order.status = OrderStatus.REJECTED
            logger.warning(f"订单拒绝: {order.order_id} — {check}")
            return order

        self._pending_orders[order.order_id] = order
        order.status = OrderStatus.SUBMITTED
        logger.info(f"订单提交: {order.order_id} {order.side.value} {order.code} {order.quantity}股")
        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        order = self._pending_orders.get(order_id)
        if order and not order.is_finished:
            order.status = OrderStatus.CANCELLED
            order.update_time = datetime.now()
            logger.info(f"订单撤销: {order_id}")
            return True
        return False

    def match_order(self, order: Order, price: float, quantity: int | None = None) -> Fill | None:
        """
        以指定价格撮合订单（实时行情驱动）。

        Args:
            order: 待撮合订单
            price: 当前市价
            quantity: 成交数量(None=全部)

        Returns:
            Fill | None
        """
        fill_qty = quantity or (order.quantity - order.filled_quantity)
        if fill_qty <= 0:
            return None

        commission = max(price * fill_qty * COMMISSION_RATE, MIN_COMMISSION)
        tax = price * fill_qty * STAMP_TAX_RATE if order.side == OrderSide.SELL else 0.0

        order.filled_quantity += fill_qty
        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL
        order.avg_fill_price = (
            (order.avg_fill_price * (order.filled_quantity - fill_qty) + price * fill_qty)
            / order.filled_quantity
        )
        order.update_time = datetime.now()

        self._apply_fill(order, fill_qty, price, commission, tax)

        fill = Fill(
            fill_id=f"fill_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            order_id=order.order_id,
            code=order.code,
            side=order.side,
            quantity=fill_qty,
            price=price,
            commission=commission,
            tax=tax,
        )
        self._fills.append(fill)

        logger.info(f"模拟成交: {order.code} {order.side.value} {fill_qty}股 @{price:.2f}")
        return fill

    # ------------------------------------------------------------------
    # 持仓更新
    # ------------------------------------------------------------------

    def mark_to_market(self, prices: dict[str, float]) -> None:
        """
        按市价更新持仓市值（市值计价）。

        Args:
            prices: {code: latest_price}
        """
        total_mv = 0.0
        for code, pos in self._account.positions.items():
            if code in prices and pos.quantity > 0:
                pos.current_price = prices[code]
                pos.market_value = pos.quantity * prices[code]
                pos.unrealized_pnl = (prices[code] - pos.avg_cost) * pos.quantity
            total_mv += pos.market_value

        self._account.total_asset = self._account.cash + self._account.frozen_cash + total_mv

    def end_of_day(self) -> None:
        """收盘结算：T+1解锁"""
        for pos in self._account.positions.values():
            if pos.quantity > 0:
                pos.available = pos.quantity

        # 清理已完成订单
        self._pending_orders = {
            k: v for k, v in self._pending_orders.items() if not v.is_finished
        }
        logger.debug("收盘结算完成")

    # ------------------------------------------------------------------
    # 风控统计
    # ------------------------------------------------------------------

    @property
    def daily_pnl(self) -> float:
        """当日盈亏（近似）"""
        if self._fills:
            today = datetime.now().date()
            today_fills = [f for f in self._fills if f.fill_time.date() == today]
            pnl = 0.0
            for f in today_fills:
                if f.side == OrderSide.SELL:
                    pnl += f.price * f.quantity - f.commission - f.tax
                else:
                    pnl -= f.price * f.quantity + f.commission
            return pnl
        return 0.0

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _apply_fill(self, order: Order, qty: int, price: float, commission: float, tax: float) -> None:
        total = price * qty + commission + tax

        if order.side == OrderSide.BUY:
            self._account.cash -= total
            self._account.frozen_cash = max(0, self._account.frozen_cash - total)

            pos = self._account.positions.get(order.code)
            if pos is None:
                pos = Position(code=order.code)
                self._account.positions[order.code] = pos

            old_cost = pos.avg_cost * pos.quantity
            pos.quantity += qty
            pos.avg_cost = (old_cost + price * qty) / pos.quantity if pos.quantity > 0 else 0

        elif order.side == OrderSide.SELL:
            self._account.cash += price * qty - commission - tax

            pos = self._account.positions.get(order.code)
            if pos:
                pnl = (price - pos.avg_cost) * qty
                pos.quantity -= qty
                pos.available -= qty
                pos.realized_pnl += pnl
                self._account.realized_pnl += pnl

                if pos.quantity <= 0:
                    del self._account.positions[order.code]

        mv = sum(p.market_value for p in self._account.positions.values())
        self._account.total_asset = self._account.cash + self._account.frozen_cash + mv

    def _check_order(self, order: Order) -> str | None:
        if order.side == OrderSide.BUY:
            required = order.price * order.quantity + max(
                order.price * order.quantity * COMMISSION_RATE, MIN_COMMISSION
            )
            if self._account.cash < required:
                return f"资金不足: 需要{required:.2f}，可用{self._account.cash:.2f}"
        elif order.side == OrderSide.SELL:
            pos = self._account.positions.get(order.code)
            if pos is None or pos.available < order.quantity:
                return f"持仓不足: {pos.available if pos else 0} < {order.quantity}"
        return None
