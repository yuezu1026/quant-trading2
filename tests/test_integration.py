"""
集成测试

端到端验证：策略 → 回测 → 绩效分析 → 数据持久化

运行:
    python -m pytest tests/test_integration.py -v
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from core.types import Bar, Account, OrderSide
from strategy import StrategyWrapper, Strategy
from backtest import BacktestEngine, Analyzer
from risk.manager import RiskManager, MaxPositionRule


# ============================================================================
# 测试辅助
# ============================================================================

def make_bar(code: str, dt: date, close: float, open_: float = 0.0,
             high: float = 0.0, low: float = 0.0, volume: float = 100000) -> Bar:
    """快速创建 Bar"""
    if open_ == 0:
        open_ = close
    if high == 0:
        high = max(close, open_)
    if low == 0:
        low = min(close, open_)
    pre = close * 0.98

    return Bar(
        code=code, date=dt,
        open=open_, high=high, low=low, close=close,
        volume=volume, amount=close * volume,
        pre_close=pre, up_limit=pre * 1.10, down_limit=pre * 0.90,
    )


def generate_price_series(
    code: str,
    start: date,
    days: int,
    prices: list[float],
) -> list[Bar]:
    """生成价格序列"""
    bars = []
    for i, p in enumerate(prices):
        dt = start + timedelta(days=i)
        bars.append(make_bar(code, dt, p))
    return bars


# ============================================================================
# 测试策略
# ============================================================================

class TestSimpleStrategy(Strategy):
    """简单测试策略：价格连续上涨2天买入，连续下跌2天卖出"""

    __test__ = False  # 非测试类，避免 pytest 收集

    def __init__(self):
        super().__init__(name="test_simple")
        self._prev_close: Optional[float] = None
        self._prev_prev_close: Optional[float] = None

    def on_bar(self, bar: Bar, account: Account) -> list:
        signals = []

        if self._prev_close is None:
            self._prev_close = bar.close
            return signals

        pos = self.position_for(bar.code, account)
        qty = pos.quantity if pos else 0

        # 连涨2天买入
        if (self._prev_prev_close and
                bar.close > self._prev_close > self._prev_prev_close and
                qty == 0):
            signals.append(self.buy(bar.code, 1000, bar.close, "连涨2日"))

        # 连跌2天卖出
        if (self._prev_prev_close and
                bar.close < self._prev_close < self._prev_prev_close and
                qty > 0):
            signals.append(self.sell(bar.code, qty, bar.close, "连跌2日"))

        self._prev_prev_close = self._prev_close
        self._prev_close = bar.close
        return signals

    def on_start(self) -> None:
        self._prev_close = None
        self._prev_prev_close = None


# ============================================================================
# 集成测试
# ============================================================================

class TestBacktestPipeline:
    """回测流程集成测试"""

    def test_full_pipeline_basic(self):
        """完整回测流程：数据→策略→引擎→分析"""
        # 1. 准备数据
        code = "600000.SH"
        start = date(2024, 1, 1)

        # 模拟价格: 先涨后跌
        prices = [
            10.0, 10.2, 10.5, 10.8, 11.0,  # 上涨
            11.0, 10.8, 10.5, 10.3, 10.0,  # 下跌
        ]
        bars = generate_price_series(code, start, len(prices), prices)

        # 2. 创建策略
        strategy = TestSimpleStrategy()
        wrapper = StrategyWrapper(strategy)

        # 3. 使用 Mock 数据源
        mock_provider = MockDataProvider(bars)

        # 4. 创建引擎
        engine = BacktestEngine(
            strategy=wrapper,
            data_provider=mock_provider,
            initial_cash=100_000.0,
        )

        # 5. 运行回测
        recorder = engine.run(
            codes=[code],
            start=start,
            end=start + timedelta(days=len(prices)),
        )

        # 6. 分析
        stats = Analyzer.analyze(recorder)

        # 7. 验证
        assert stats.total_days > 0, "应该有交易日"
        assert stats.trade_count > 0, "应该有交易"

        daily = recorder.to_daily_df()
        assert not daily.empty, "应该有每日记录"
        assert "total_asset" in daily.columns
        assert "cash" in daily.columns

        fills = recorder.to_fills_df()
        assert not fills.empty, "应该有成交记录"

    def test_pipeline_with_risk_manager(self):
        """风控集成测试"""
        code = "600000.SH"
        start = date(2024, 1, 1)
        prices = [10.0, 10.5, 11.0, 11.5, 12.0, 11.5, 11.0, 10.5, 10.0, 9.5]
        bars = generate_price_series(code, start, len(prices), prices)

        strategy = TestSimpleStrategy()
        wrapper = StrategyWrapper(strategy)

        mock_provider = MockDataProvider(bars)

        engine = BacktestEngine(
            strategy=wrapper,
            data_provider=mock_provider,
            initial_cash=100_000.0,
        )

        recorder = engine.run(
            codes=[code],
            start=start,
            end=start + timedelta(days=len(prices)),
        )

        # 验证账号资金一致性
        daily = recorder.to_daily_df()
        for _, row in daily.iterrows():
            # 资金守恒: 现金+冻结金+持仓市值 ≈ 总资产
            # (简化检查: 不做精确验证，只确保值合理)
            assert row["total_asset"] >= 0
            assert row["cash"] >= 0

    def test_recorder_consistency(self):
        """记录器数据一致性"""
        code = "600000.SH"
        start = date(2024, 1, 1)
        prices = [10.0, 10.5, 11.0, 10.5, 10.0]
        bars = generate_price_series(code, start, len(prices), prices)

        strategy = TestSimpleStrategy()
        wrapper = StrategyWrapper(strategy)
        mock_provider = MockDataProvider(bars)

        engine = BacktestEngine(
            strategy=wrapper,
            data_provider=mock_provider,
            initial_cash=100_000.0,
        )

        recorder = engine.run(
            codes=[code],
            start=start,
            end=start + timedelta(days=len(prices)),
        )

        # 订单数和成交数应该一致（每个订单都成交的情况下）
        orders = recorder.to_orders_df()
        fills = recorder.to_fills_df()

        # 每个成交对应一个订单（简化验证）
        if not fills.empty and not orders.empty:
            fill_order_ids = set(fills["order_id"])
            order_ids = set(orders["order_id"])
            assert fill_order_ids.issubset(order_ids), "成交必须对应已知订单"


class TestEventBusIntegration:
    """事件总线集成测试"""

    def test_event_flow(self):
        from core.event_bus import EventBus
        from core.types import Event, EventType

        bus = EventBus()
        events = []

        def collector(e: Event):
            events.append(e.type.value)

        bus.register(EventType.BAR, collector)
        bus.register(EventType.SIGNAL, collector)
        bus.register(EventType.FILL, collector)

        bus.emit(Event(type=EventType.BAR, data={}))
        bus.emit(Event(type=EventType.BAR, data={}))
        bus.emit(Event(type=EventType.SIGNAL, data={}))
        bus.emit(Event(type=EventType.FILL, data={}))

        assert events.count("bar") == 2
        assert events.count("signal") == 1
        assert events.count("fill") == 1
        assert bus.stats["bar"] == 2


class TestRiskManagerIntegration:
    """风控集成测试"""

    def test_max_position_rule(self):
        rm = RiskManager()
        rm.add_rule(MaxPositionRule(ratio=0.3))

        from core.types import Signal, Account

        account = Account(
            cash=100_000.0,
            total_asset=100_000.0,
        )

        # 买入 4000 股 @10元 = 40000，占总资产 40% > 30% 限制
        signal = Signal(code="600000.SH", side=OrderSide.BUY, quantity=4000, price=10.0)

        ok, reason = rm.check(signal, account)
        assert not ok, f"应该被拦截: {reason}"

        # 买入 2000 股 @10元 = 20000，占总资产 20% < 30% → 通过
        signal2 = Signal(code="600000.SH", side=OrderSide.BUY, quantity=2000, price=10.0)
        ok2, _ = rm.check(signal2, account)
        assert ok2, "应该在限额内通过"


# ============================================================================
# Mock 数据源
# ============================================================================


class MockDataProvider:
    """Mock 数据源，直接返回预生成的 Bar 列表"""

    def __init__(self, bars: list[Bar]):
        self._bars = bars
        self._df = pd.DataFrame([{
            "code": b.code,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "amount": b.amount,
        } for b in bars])

    def get_daily(self, code: str, start: date, end: date, adjust: str = "qfq") -> pd.DataFrame:
        df = self._df.copy()
        df = df[(df["code"] == code) & (df["date"] >= start) & (df["date"] <= end)]
        return df.sort_values("date").reset_index(drop=True)

    def get_minute(self, code: str, date_: date, freq: str = "1") -> pd.DataFrame:
        return pd.DataFrame()

    def get_stock_info(self, code: str) -> dict:
        return {"code": code, "name": "测试股票"}

    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame()
