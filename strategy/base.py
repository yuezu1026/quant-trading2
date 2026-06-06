"""
策略基类

所有策略必须继承此基类，只需实现 on_bar() 方法。
同一个策略类可在回测、模拟、实盘三种模式下运行，无需修改代码。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.types import Bar, Signal, Fill, RiskAlert, Account, Position


class Strategy(ABC):
    """
    策略基类 — 事件驱动架构的核心抽象。

    子类需要实现:
        on_bar(bar, account) -> list[Signal] | None

    可选覆盖:
        on_fill(fill)     — 成交回调
        on_risk_alert(a)  — 风控告警回调
        on_start()        — 策略启动
        on_stop()         — 策略停止
    """

    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__
        self._params: dict = {}
        self._is_running = False

    # ------------------------------------------------------------------
    # 核心回调
    # ------------------------------------------------------------------

    @abstractmethod
    def on_bar(self, bar: Bar, account: Account) -> list[Signal]:
        """
        K线数据回调 — 策略的核心逻辑。

        每次收到一根完整的K线时调用。
        策略分析 bar 和当前 account 状态，返回交易信号列表。

        Args:
            bar: 当前K线数据
            account: 当前账户状态（资金、持仓）

        Returns:
            Signal 列表，无信号时返回空列表
        """
        ...

    def on_fill(self, fill: Fill, account: Account) -> None:
        """成交回调（可选覆盖）"""
        pass

    def on_risk_alert(self, alert: RiskAlert, account: Account) -> None:
        """风控告警回调（可选覆盖）"""
        pass

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        """策略启动时调用"""
        self._is_running = True

    def on_stop(self) -> None:
        """策略停止时调用"""
        self._is_running = False

    # ------------------------------------------------------------------
    # 参数管理
    # ------------------------------------------------------------------

    def set_params(self, **kwargs) -> "Strategy":
        """设置策略参数（链式调用）"""
        self._params.update(kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)
        return self

    @property
    def params(self) -> dict:
        return self._params.copy()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def buy(
        code: str,
        quantity: int,
        price: Optional[float] = None,
        reason: str = "",
        confidence: float = 1.0,
    ) -> Signal:
        """生成买入信号"""
        from core.types import OrderType

        return Signal(
            code=code,
            side="buy",
            quantity=quantity,
            price=price,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            reason=reason,
            confidence=confidence,
        )

    @staticmethod
    def sell(
        code: str,
        quantity: int,
        price: Optional[float] = None,
        reason: str = "",
        confidence: float = 1.0,
    ) -> Signal:
        """生成卖出信号"""
        from core.types import OrderType

        return Signal(
            code=code,
            side="sell",
            quantity=quantity,
            price=price,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            reason=reason,
            confidence=confidence,
        )

    @staticmethod
    def position_for(code: str, account: Account) -> Optional[Position]:
        """获取某只股票的持仓"""
        return account.positions.get(code)

    def has_position(self, code: str, account: Account) -> bool:
        """是否持有某股票"""
        pos = self.position_for(code, account)
        return pos is not None and pos.quantity > 0


class StrategyWrapper:
    """
    策略包装器 — 为策略提供预计算数据缓存等增强能力。

    引擎不直接与 Strategy 交互，而是通过 StrategyWrapper。
    方便后续扩展（如预计算因子、并行信号生成等）。
    """

    def __init__(self, strategy: Strategy):
        self._strategy = strategy
        self._indicator_cache: dict = {}

    @property
    def name(self) -> str:
        return self._strategy.name

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    def on_bar(self, bar: Bar, account: Account) -> list[Signal]:
        """带缓存的 on_bar 调用"""
        return self._strategy.on_bar(bar, account) or []

    def on_fill(self, fill: Fill, account: Account) -> None:
        self._strategy.on_fill(fill, account)

    def on_risk_alert(self, alert: RiskAlert, account: Account) -> None:
        self._strategy.on_risk_alert(alert, account)

    def on_start(self) -> None:
        self._strategy.on_start()

    def on_stop(self) -> None:
        self._strategy.on_stop()

    def set_params(self, **kwargs) -> "StrategyWrapper":
        self._strategy.set_params(**kwargs)
        return self

    @property
    def params(self) -> dict:
        return self._strategy.params
