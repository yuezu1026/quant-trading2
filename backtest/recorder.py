"""
回测记录器

记录回测过程中的所有关键数据：每日资产、订单、成交、持仓变化。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from core.types import Order, Fill, Account


class Recorder:
    """回测记录器"""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """清空所有记录"""
        self._daily: list[dict] = []       # 每日资产快照
        self._orders: list[dict] = []      # 订单记录
        self._fills: list[dict] = []       # 成交记录
        self._positions: list[dict] = []   # 每日持仓

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def record_daily(self, day: date, account: Account) -> None:
        """记录每日账户快照"""
        self._daily.append({
            "date": day,
            "cash": account.cash,
            "frozen_cash": account.frozen_cash,
            "total_asset": account.total_asset,
            "realized_pnl": account.realized_pnl,
            "position_count": len(account.positions),
        })

        # 记录每日持仓
        for code, pos in account.positions.items():
            if pos.quantity > 0:
                self._positions.append({
                    "date": day,
                    "code": code,
                    "quantity": pos.quantity,
                    "avg_cost": pos.avg_cost,
                    "current_price": pos.current_price,
                    "market_value": pos.market_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                })

    def record_order(self, order: Order) -> None:
        """记录订单"""
        self._orders.append({
            "order_id": order.order_id,
            "code": order.code,
            "side": order.side.value,
            "quantity": order.quantity,
            "price": order.price,
            "order_type": order.order_type.value,
            "status": order.status.value,
            "create_time": order.create_time,
            "reason": order.signal.reason if order.signal else "",
        })

    def record_fill(self, fill: Fill) -> None:
        """记录成交"""
        self._fills.append({
            "fill_id": fill.fill_id,
            "order_id": fill.order_id,
            "code": fill.code,
            "side": fill.side.value,
            "quantity": fill.quantity,
            "price": fill.price,
            "commission": fill.commission,
            "tax": fill.tax,
            "fill_time": fill.fill_time,
        })

    # ------------------------------------------------------------------
    # DataFrame 导出
    # ------------------------------------------------------------------

    def to_daily_df(self) -> pd.DataFrame:
        """导出每日资产快照为 DataFrame"""
        if not self._daily:
            return pd.DataFrame()
        return pd.DataFrame(self._daily)

    def to_fills_df(self) -> pd.DataFrame:
        """导出成交记录为 DataFrame"""
        if not self._fills:
            return pd.DataFrame()
        return pd.DataFrame(self._fills)

    def to_orders_df(self) -> pd.DataFrame:
        """导出订单记录为 DataFrame"""
        if not self._orders:
            return pd.DataFrame()
        return pd.DataFrame(self._orders)

    def to_positions_df(self) -> pd.DataFrame:
        """导出每日持仓为 DataFrame"""
        if not self._positions:
            return pd.DataFrame()
        return pd.DataFrame(self._positions)

    # ------------------------------------------------------------------
    # 快捷属性
    # ------------------------------------------------------------------

    @property
    def daily(self) -> pd.DataFrame:
        return self.to_daily_df()

    @property
    def fills(self) -> pd.DataFrame:
        return self.to_fills_df()

    @property
    def total_return(self) -> float:
        """总收益率"""
        if self._daily:
            start_asset = self._daily[0]["total_asset"]
            end_asset = self._daily[-1]["total_asset"]
            if start_asset > 0:
                return (end_asset - start_asset) / start_asset
        return 0.0

    @property
    def trade_count(self) -> int:
        """成交次数"""
        return len(self._fills)

    @property
    def win_count(self) -> int:
        """盈利次数（粗略：卖出成交的 tax > 0 为卖出）"""
        return len([f for f in self._fills if f["side"] == "sell" and f["tax"] > 0])

    def __repr__(self) -> str:
        return (
            f"Recorder(days={len(self._daily)}, "
            f"trades={self.trade_count}, "
            f"return={self.total_return:.2%})"
        )
