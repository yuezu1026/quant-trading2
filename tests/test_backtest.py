"""
回测引擎单元测试

运行: python -m pytest tests/test_backtest.py -v
"""
from datetime import date

import pytest

from core.types import (
    Bar, Order, OrderSide, OrderStatus,
)
from backtest.broker import SimulatedBroker


class TestSimulatedBroker:
    """模拟券商测试"""

    @pytest.fixture
    def broker(self):
        return SimulatedBroker(initial_cash=100_000.0)

    @pytest.fixture
    def sample_bar(self):
        return Bar(
            code="600000.SH",
            date=date(2024, 1, 15),
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            volume=1000000,
            amount=10200000.0,
            pre_close=10.0,
            up_limit=11.0,
            down_limit=9.0,
        )

    def test_initial_account(self, broker):
        assert broker.account.cash == 100_000.0
        assert broker.account.total_asset == 100_000.0
        assert len(broker.account.positions) == 0

    def test_submit_buy_order(self, broker, sample_bar):
        order = Order(
            order_id="ord_001",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.2,
        )
        broker.submit_order(order)

        # 订单状态更新为一笔
        # 注意：在盘中买入，冻结资金在撮合时扣除
        assert order.status == OrderStatus.SUBMITTED

    def test_match_buy_order(self, broker, sample_bar):
        order = Order(
            order_id="ord_001",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.2,
        )
        broker.submit_order(order)
        fills = broker.match(sample_bar)

        assert len(fills) == 1
        assert fills[0].quantity == 1000
        assert fills[0].price == 10.2

        # 检查账户
        pos = broker.account.positions.get("600000.SH")
        assert pos is not None
        assert pos.quantity == 1000
        # T+1: 今日买入的不可卖
        assert pos.available == 0

    def test_t1_rule(self, broker, sample_bar):
        """测试 T+1 规则"""
        # Day 1: 买入
        buy_order = Order(
            order_id="ord_buy",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.0,
        )
        broker.submit_order(buy_order)
        broker.match(sample_bar)

        # 当日不可卖
        pos = broker.account.positions["600000.SH"]
        assert pos.quantity == 1000
        assert pos.available == 0

        # 尝试卖出（应该被拒绝）
        sell_order = Order(
            order_id="ord_sell",
            code="600000.SH",
            side=OrderSide.SELL,
            quantity=1000,
            price=10.5,
        )
        broker.submit_order(sell_order)
        assert sell_order.status == OrderStatus.REJECTED

        # Day 2: 结算后
        bar_day2 = Bar(
            code="600000.SH",
            date=date(2024, 1, 16),
            open=10.3, high=10.5, low=10.2, close=10.4,
            volume=500000, amount=5200000.0,
        )
        broker.end_of_day(bar_day2)

        # 现在应该可以卖了
        pos = broker.account.positions["600000.SH"]
        assert pos.available == 1000

        sell_order2 = Order(
            order_id="ord_sell2",
            code="600000.SH",
            side=OrderSide.SELL,
            quantity=1000,
            price=10.4,
        )
        broker.submit_order(sell_order2)
        fills = broker.match(bar_day2)

        assert len(fills) == 1
        assert broker.account.positions.get("600000.SH") is None  # 清仓

    def test_commission_and_tax(self, broker, sample_bar):
        """测试手续费和印花税"""
        # 买入：仅佣金
        buy_order = Order(
            order_id="ord_buy",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.0,
        )
        broker.submit_order(buy_order)
        fills = broker.match(sample_bar)

        assert fills[0].commission > 0  # 有佣金
        assert fills[0].tax == 0.0       # 买入无印花税

        # T+1 解锁
        broker.end_of_day(sample_bar)

        # 卖出：佣金+印花税
        sell_order = Order(
            order_id="ord_sell",
            code="600000.SH",
            side=OrderSide.SELL,
            quantity=1000,
            price=10.0,
        )
        broker.submit_order(sell_order)
        fills = broker.match(sample_bar)

        assert fills[0].commission > 0
        assert fills[0].tax > 0  # 卖出有印花税

    def test_insufficient_cash(self, broker, sample_bar):
        """资金不足时拒绝"""
        order = Order(
            order_id="ord_big",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=100000,  # 1000万,远超10万资金
            price=100.0,
        )
        broker.submit_order(order)
        assert order.status == OrderStatus.REJECTED

    def test_reset(self, broker, sample_bar):
        """重置后状态清空"""
        order = Order(
            order_id="ord_001",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.0,
        )
        broker.submit_order(order)
        broker.match(sample_bar)

        broker.reset()
        assert broker.account.cash == 100_000.0
        assert len(broker.account.positions) == 0
        assert len(broker.fills) == 0
