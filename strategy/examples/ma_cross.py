"""
双均线交叉策略 — 示例策略

规则:
- 当短期均线上穿长期均线 → 全仓买入
- 当短期均线下穿长期均线 → 全部卖出
- 同一时间只持有一只股票

演示了策略基类的标准用法。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.types import Bar, Signal, Account, Fill
from strategy.base import Strategy
from strategy.indicators import sma, cross_up, cross_down


class MACrossStrategy(Strategy):
    """
    双均线交叉策略。

    参数:
        fast_period: 短期均线周期 (默认5)
        slow_period: 长期均线周期 (默认20)
        fixed_quantity: 固定交易数量(股)，0表示用全部资金计算 (默认0)
    """

    def __init__(
        self,
        fast_period: int = 5,
        slow_period: int = 20,
        fixed_quantity: int = 0,
    ):
        super().__init__(name=f"MA_Cross_{fast_period}_{slow_period}")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.fixed_quantity = fixed_quantity

        # 状态：缓存历史收盘价用于计算均线
        self._prices: list[float] = []
        self._prev_fast: float = 0.0
        self._prev_slow: float = 0.0

    def on_bar(self, bar: Bar, account: Account) -> list[Signal]:
        signals = []

        # 跳过停牌或无效数据
        if bar.close <= 0 or bar.volume <= 0:
            return signals

        # 累加价格历史
        self._prices.append(bar.close)
        if len(self._prices) > max(self.slow_period, self.fast_period) + 1:
            self._prices.pop(0)

        series = pd.Series(self._prices)

        # 计算均线
        fast = sma(series, self.fast_period).iloc[-1]
        slow = sma(series, self.slow_period).iloc[-1]

        if np.isnan(fast) or np.isnan(slow):
            # 记录当前值供下次使用
            if len(self._prices) > self.fast_period:
                self._prev_fast = fast if not np.isnan(fast) else self._prev_fast
                self._prev_slow = slow if not np.isnan(slow) else self._prev_slow
            return signals

        # 判断交叉
        current_cross_up = fast > slow and self._prev_fast <= self._prev_slow and self._prev_fast > 0
        current_cross_down = fast < slow and self._prev_fast >= self._prev_slow

        # 更新前值
        self._prev_fast = fast
        self._prev_slow = slow

        # 生成信号
        pos = self.position_for(bar.code, account)
        current_qty = pos.quantity if pos else 0

        if current_cross_up and current_qty == 0:
            quantity = self._calc_buy_quantity(bar.close, account)
            signals.append(self.buy(
                code=bar.code,
                quantity=quantity,
                price=bar.close,
                reason=f"金叉: MA{self.fast_period}={fast:.2f} ↑ MA{self.slow_period}={slow:.2f}",
            ))

        elif current_cross_down and current_qty > 0:
            signals.append(self.sell(
                code=bar.code,
                quantity=current_qty,
                price=bar.close,
                reason=f"死叉: MA{self.fast_period}={fast:.2f} ↓ MA{self.slow_period}={slow:.2f}",
            ))

        return signals

    def _calc_buy_quantity(self, price: float, account: Account) -> int:
        """计算买入数量（100股的整数倍）"""
        if self.fixed_quantity > 0:
            return (self.fixed_quantity // 100) * 100

        available = account.cash * 0.95  # 留5%缓冲
        shares = int(available / price)
        return (shares // 100) * 100

    def on_start(self) -> None:
        self._prices = []
        self._prev_fast = 0.0
        self._prev_slow = 0.0
