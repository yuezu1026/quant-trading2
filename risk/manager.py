"""
风控管理器

在订单提交前进行多道风控检查。
所有规则都是"否决制"——任一规则不通过则拦截订单。
"""
from __future__ import annotations

import logging
from typing import Optional

from core.types import Signal, Account

logger = logging.getLogger(__name__)


class RiskManager:
    """
    风控管理器。

    使用方式:
        rm = RiskManager()
        rm.add_rule(MaxPositionRule(ratio=0.3))
        rm.add_rule(StopLossRule(pct=0.05))
        ...
        ok, reason = rm.check(signal, account)
    """

    def __init__(self):
        self._rules: list[RiskRule] = []

    def add_rule(self, rule: "RiskRule") -> "RiskManager":
        """添加风控规则"""
        self._rules.append(rule)
        return self

    def check(self, signal: Signal, account: Account) -> tuple[bool, Optional[str]]:
        """
        检查信号是否合规。

        Returns:
            (通过, 拒绝原因) — 通过时拒绝原因为 None
        """
        for rule in self._rules:
            if not rule.check(signal, account):
                reason = rule.reason(signal, account)
                logger.warning(f"风控拦截: {rule.name} - {reason}")
                return False, reason
        return True, None

    def check_all(
        self, signals: list[Signal], account: Account
    ) -> list[tuple[Signal, bool, Optional[str]]]:
        """批量检查信号"""
        return [(s, *self.check(s, account)) for s in signals]


class RiskRule:
    """风控规则基类"""

    name: str = "base_rule"

    def check(self, signal: Signal, account: Account) -> bool:
        """检查是否通过，True=通过"""
        return True

    def reason(self, signal: Signal, account: Account) -> str:
        """返回拒绝原因"""
        return ""


# ============================================================================
# 常用规则
# ============================================================================

class MaxPositionRule(RiskRule):
    """单票最大仓位限制"""

    name = "max_position"

    def __init__(self, ratio: float = 0.3):
        """
        Args:
            ratio: 单票最大仓位占总资产的比例
        """
        self.ratio = ratio

    def check(self, signal: Signal, account: Account) -> bool:
        if signal.side.value == "sell":
            return True  # 卖出不限制

        pos = account.positions.get(signal.code)
        current_mv = pos.market_value if pos else 0
        new_mv = current_mv + signal.price * signal.quantity if signal.price else current_mv

        return new_mv <= account.total_asset * self.ratio

    def reason(self, signal: Signal, account: Account) -> str:
        return f"单票仓位超限(>{self.ratio:.0%})"


class StopLossRule(RiskRule):
    """硬止损规则"""

    name = "stop_loss"

    def __init__(self, pct: float = 0.10):
        """
        Args:
            pct: 止损比例，默认-10%
        """
        self.pct = pct

    def check(self, signal: Signal, account: Account) -> bool:
        pos = account.positions.get(signal.code)
        if pos is None or pos.quantity == 0:
            return True

        # 计算浮动亏损比例
        if pos.avg_cost > 0:
            loss_pct = (pos.current_price - pos.avg_cost) / pos.avg_cost
            if loss_pct <= -self.pct:
                return False  # 触发止损，阻止进一步买入
        return True

    def reason(self, signal: Signal, account: Account) -> str:
        return f"触发止损(浮动亏损>{self.pct:.0%})"


class DailyLossRule(RiskRule):
    """日内最大亏损限制"""

    name = "daily_loss"

    def __init__(self, max_loss: float = 0.05):
        """
        Args:
            max_loss: 日内最大亏损占初始资产的比例
        """
        self.max_loss = max_loss
        self._day_start_asset: float = 0.0
        self._current_day: Optional[str] = None

    def update_day(self, date_str: str, asset: float) -> None:
        """每日更新基准"""
        if date_str != self._current_day:
            self._current_day = date_str
            self._day_start_asset = asset

    def check(self, signal: Signal, account: Account) -> bool:
        if self._day_start_asset <= 0:
            return True
        loss_pct = (account.total_asset - self._day_start_asset) / self._day_start_asset
        return loss_pct > -self.max_loss

    def reason(self, signal: Signal, account: Account) -> str:
        return f"日内亏损超限(>{self.max_loss:.0%})"


class BlacklistRule(RiskRule):
    """黑名单检查"""

    name = "blacklist"

    def __init__(self, blacklist: list[str] | None = None):
        self.blacklist = set(blacklist or [])

    def add(self, code: str) -> None:
        self.blacklist.add(code)

    def check(self, signal: Signal, account: Account) -> bool:
        return signal.code not in self.blacklist

    def reason(self, signal: Signal, account: Account) -> str:
        return f"{signal.code} 在黑名单中"
