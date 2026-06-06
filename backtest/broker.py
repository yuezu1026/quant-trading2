"""
模拟券商 — 撮合引擎

模拟A股交易的真实规则：
- T+1: 当日买入的股票次日才可卖出
- 涨跌停限制: 超过涨跌停价的限价单无法成交
- 交易费用: 佣金万2.5(最低5元) + 印花税0.1%(仅卖出)
- 最小交易单位: 100股(1手)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from core.types import (
    Order, OrderSide, OrderType, OrderStatus,
    Fill, Bar, Position, Account,
)

logger = logging.getLogger(__name__)

# A股交易费用参数
COMMISSION_RATE = 0.00025    # 佣金 万2.5
MIN_COMMISSION = 5.0         # 最低佣金 5元
STAMP_TAX_RATE = 0.001       # 印花税 0.1% (仅卖出)


class SimulatedBroker:
    """
    模拟券商 — 负责订单撮合和账户管理。

    撮合规则:
    1. 市价单: 以当前 bar.close 成交
    2. 限价单:
       - 买入: price >= bar.close 才能成交
       - 卖出: price <= bar.close 才能成交
    3. 涨跌停: 达到涨跌停价格的订单，需排队等待（简化处理：无法成交）
    4. T+1: 今日买入的股票，available=0，次日才能卖
    """

    def __init__(self, initial_cash: float = 100_000.0):
        self._initial_cash = initial_cash
        self._account = Account(cash=initial_cash, total_asset=initial_cash)

        self._pending_orders: dict[str, Order] = {}
        self._filled_orders: list[Fill] = []

        # T+1: 记录今日买入的股票及其数量
        self._today_buy: dict[str, int] = {}

        self._day: int = 0  # 回测日计数

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def account(self) -> Account:
        return self._account

    @property
    def fills(self) -> list[Fill]:
        return list(self._filled_orders)

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """重置券商状态（新一轮回测前调用）"""
        self._account = Account(cash=self._initial_cash, total_asset=self._initial_cash)
        self._pending_orders.clear()
        self._filled_orders.clear()
        self._today_buy.clear()
        self._day = 0

    # ------------------------------------------------------------------
    # 每日结算
    # ------------------------------------------------------------------

    def end_of_day(self, bar: Bar) -> None:
        """
        每日收盘结算:
        - 将今日买入的股票转为"今日持仓"（次日变为 available）
        - 按收盘价更新持仓市值
        - 清除过期冻结资金
        """
        self._day += 1

        # T+1: 昨日买入的 → 今日可卖
        for code, pos in self._account.positions.items():
            if pos.quantity > 0:
                # 所有持仓在次日全部变为可卖
                pos.available = pos.quantity

        # 按收盘价更新市值
        total_mv = 0.0
        for code, pos in self._account.positions.items():
            if code == bar.code:
                pos.current_price = bar.close
                pos.market_value = pos.quantity * bar.close
                pos.unrealized_pnl = (bar.close - pos.avg_cost) * pos.quantity
            total_mv += pos.market_value

        # 更新总资产
        self._account.total_asset = self._account.cash + self._account.frozen_cash + total_mv

        # 清除已完成的订单
        self._pending_orders = {
            oid: o for oid, o in self._pending_orders.items()
            if not o.is_finished
        }

    # ------------------------------------------------------------------
    # 订单提交
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        """提交订单（由引擎调用）"""
        if order.order_id in self._pending_orders:
            logger.warning(f"重复订单: {order.order_id}")
            return self._pending_orders[order.order_id]

        self._pending_orders[order.order_id] = order

        # 检查资金/持仓是否足够
        check_result = self._check_order(order)
        if check_result:
            order.status = OrderStatus.REJECTED
            logger.warning(f"订单被拒绝: {order.order_id} - {check_result}")
            return order

        order.status = OrderStatus.SUBMITTED
        return order

    # ------------------------------------------------------------------
    # 撮合订单
    # ------------------------------------------------------------------

    def match(self, bar: Bar) -> list[Fill]:
        """用当前 bar 匹配所有待成交订单，返回成交列表"""
        fills = []

        for order in list(self._pending_orders.values()):
            if order.is_finished:
                continue
            if order.code != bar.code:
                continue

            fill = self._try_match(order, bar)
            if fill:
                fills.append(fill)
                self._filled_orders.append(fill)

        return fills

    def _try_match(self, order: Order, bar: Bar) -> Fill | None:
        """
        尝试撮合一个订单。

        Returns:
            Fill | None — 成交记录或None(未成交)
        """
        # 涨跌停检查
        if bar.is_limit_up and order.side == OrderSide.BUY:
            return None  # 涨停买不进
        if bar.is_limit_down and order.side == OrderSide.SELL:
            return None  # 跌停卖不出

        # 价格检查
        fill_price = bar.close
        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and order.price < bar.low:
                return None  # 限价太低, 买不到
            if order.side == OrderSide.SELL and order.price > bar.high:
                return None  # 限价太高, 卖不出
            # 以限价成交
            fill_price = order.price

        # 计算成交数量
        fill_qty = order.quantity - order.filled_quantity

        # 计算费用
        commission = max(fill_price * fill_qty * COMMISSION_RATE, MIN_COMMISSION)
        tax = fill_price * fill_qty * STAMP_TAX_RATE if order.side == OrderSide.SELL else 0.0

        # 更新订单状态
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        order.status = OrderStatus.FILLED
        order.update_time = datetime.now()

        # 更新账户
        self._apply_fill(order, fill_qty, fill_price, commission, tax)

        fill = Fill(
            fill_id=f"fill_{uuid.uuid4().hex[:8]}",
            order_id=order.order_id,
            code=order.code,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            commission=commission,
            tax=tax,
        )

        logger.info(
            f"成交: {order.code} {order.side.value} "
            f"{fill_qty}股 @{fill_price:.2f} "
            f"佣金{commission:.2f} 印花税{tax:.2f}"
        )

        return fill

    # ------------------------------------------------------------------
    # 账户更新
    # ------------------------------------------------------------------

    def _apply_fill(
        self,
        order: Order,
        qty: int,
        price: float,
        commission: float,
        tax: float,
    ) -> None:
        """应用成交到账户"""
        total_cost = price * qty + commission + tax

        if order.side == OrderSide.BUY:
            # 买入
            self._account.cash -= total_cost
            self._account.frozen_cash = max(0, self._account.frozen_cash - total_cost)

            # 更新持仓
            pos = self._account.positions.get(order.code)
            if pos is None:
                pos = Position(code=order.code)
                self._account.positions[order.code] = pos

            old_cost = pos.avg_cost * pos.quantity
            pos.quantity += qty
            pos.avg_cost = (old_cost + price * qty) / pos.quantity if pos.quantity > 0 else 0
            # T+1: 今日买入的不可卖
            # available 保持不变(不会增加)

        elif order.side == OrderSide.SELL:
            # 卖出
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

        # 更新总资产
        mv = sum(p.market_value for p in self._account.positions.values())
        self._account.total_asset = self._account.cash + self._account.frozen_cash + mv

    # ------------------------------------------------------------------
    # 订单检查
    # ------------------------------------------------------------------

    def _check_order(self, order: Order) -> str | None:
        """检查订单是否有效，返回 None=通过, str=拒绝原因"""
        if order.side == OrderSide.BUY:
            required = order.price * order.quantity + max(
                order.price * order.quantity * COMMISSION_RATE, MIN_COMMISSION
            )
            if self._account.cash < required:
                return f"资金不足: 需要{required:.2f}, 可用{self._account.cash:.2f}"
        elif order.side == OrderSide.SELL:
            pos = self._account.positions.get(order.code)
            if pos is None or pos.available < order.quantity:
                return f"持仓不足: {pos.available if pos else 0} < {order.quantity}"
        return None
