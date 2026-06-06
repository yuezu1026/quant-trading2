"""
持仓管理器

负责:
- 本地持仓计算（根据成交记录）
- 与券商持仓对账（reconciliation）
- T+1 可卖数量计算
- 持仓成本核算（移动加权平均）
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from core.types import (
    OrderSide, Position, Fill, Account,
)

logger = logging.getLogger(__name__)


class PositionManager:
    """
    持仓管理器。

    双源对比模式:
    - 券商源: query_positions() 返回的权威数据
    - 本地源: 根据成交记录计算的本地预期
    - 对账: 比较两源，发现差异时以券商为准
    """

    def __init__(self):
        # 本地计算的持仓
        self._positions: dict[str, Position] = {}
        # 今日买入记录（用于 T+1 计算）
        self._today_buys: dict[str, int] = {}
        # 对账日志
        self._reconciliation_log: list[dict] = []

    # ------------------------------------------------------------------
    # 成交处理
    # ------------------------------------------------------------------

    def on_fill(self, fill: Fill) -> Position:
        """
        根据成交更新本地持仓。

        Returns:
            更新后的持仓
        """
        code = fill.code
        if code not in self._positions:
            self._positions[code] = Position(code=code)

        pos = self._positions[code]

        if fill.side == OrderSide.BUY:
            # 移动加权平均成本
            old_cost = pos.avg_cost * pos.quantity
            new_total_cost = old_cost + fill.price * fill.quantity + fill.commission
            pos.quantity += fill.quantity
            pos.avg_cost = new_total_cost / pos.quantity if pos.quantity > 0 else 0

            # T+1: 今日买入不可卖
            self._today_buys[code] = self._today_buys.get(code, 0) + fill.quantity

        elif fill.side == OrderSide.SELL:
            pos.quantity -= fill.quantity
            pos.available -= fill.quantity

            # 已实现盈亏
            pnl = (fill.price - pos.avg_cost) * fill.quantity - fill.commission - fill.tax
            pos.realized_pnl += pnl

            if pos.quantity <= 0:
                pos.avg_cost = 0.0
                pos.quantity = 0
                pos.available = 0

        pos.market_value = pos.quantity * pos.avg_cost  # 暂用成本，mark_to_market 会更新
        return pos

    # ------------------------------------------------------------------
    # 市值计价
    # ------------------------------------------------------------------

    def mark_to_market(self, prices: dict[str, float]) -> None:
        """按市价更新所有持仓市值"""
        for code, pos in self._positions.items():
            if code in prices and pos.quantity > 0:
                pos.current_price = prices[code]
                pos.market_value = pos.quantity * prices[code]
                pos.unrealized_pnl = (prices[code] - pos.avg_cost) * pos.quantity

    # ------------------------------------------------------------------
    # 日结算
    # ------------------------------------------------------------------

    def end_of_day(self) -> None:
        """收盘结算: T+1 解锁"""
        for pos in self._positions.values():
            pos.available = pos.quantity
        self._today_buys.clear()
        logger.debug("持仓日结算完成: T+1解锁")

    # ------------------------------------------------------------------
    # 对账
    # ------------------------------------------------------------------

    def reconcile(self, broker_positions: list[Position]) -> dict:
        """
        与券商持仓对账。

        Returns:
            {code: {local_qty, broker_qty, diff, matched}}
        """
        result = {}

        # 券商持仓转字典
        broker_map = {p.code: p for p in broker_positions}

        # 本地 vs 券商
        all_codes = set(self._positions.keys()) | set(broker_map.keys())

        for code in all_codes:
            local = self._positions.get(code)
            broker = broker_map.get(code)

            local_qty = local.quantity if local else 0
            broker_qty = broker.quantity if broker else 0
            diff = broker_qty - local_qty

            entry = {
                "code": code,
                "local_qty": local_qty,
                "broker_qty": broker_qty,
                "diff": diff,
                "matched": diff == 0,
                "time": datetime.now().isoformat(),
            }
            result[code] = entry

            if diff != 0:
                logger.warning(
                    f"持仓对账差异: {code} 本地={local_qty} 券商={broker_qty} 差={diff}"
                )
                self._reconciliation_log.append(entry)

                # 以券商为准修正本地
                if broker:
                    self._positions[code] = broker
                elif code in self._positions:
                    del self._positions[code]

        return result

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_position(self, code: str) -> Optional[Position]:
        return self._positions.get(code)

    def get_all_positions(self) -> list[Position]:
        """获取所有持仓"""
        return [p for p in self._positions.values() if p.quantity > 0]

    @property
    def positions(self) -> dict[str, Position]:
        return {k: v for k, v in self._positions.items() if v.quantity > 0}

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self._positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self._positions.values())

    def available_quantity(self, code: str) -> int:
        """可卖数量（考虑T+1）"""
        pos = self._positions.get(code)
        if pos is None:
            return 0
        return pos.available

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def can_sell(self, code: str, quantity: int) -> tuple[bool, str]:
        """检查是否可以卖出"""
        pos = self._positions.get(code)
        if pos is None or pos.quantity <= 0:
            return False, f"无持仓: {code}"

        if pos.available < quantity:
            return False, f"可卖不足: 需要{quantity}股, 可卖{pos.available}股 (T+1限制)"

        return True, ""
