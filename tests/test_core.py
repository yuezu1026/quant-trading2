"""
核心模块单元测试

运行: python -m pytest tests/ -v
"""
import io
from datetime import date, datetime

import pytest

from core.types import (
    Bar, Signal, Order, Fill, Position, Account,
    OrderSide, OrderType, OrderStatus, Event, EventType,
)
from core.event_bus import EventBus


class TestBar:
    def test_bar_creation(self):
        bar = Bar(
            code="600000.SH",
            date=date(2024, 1, 15),
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            volume=100000,
            amount=1020000.0,
        )
        assert bar.code == "600000.SH"
        assert bar.close == 10.2

    def test_change_pct(self):
        bar = Bar(
            code="600000.SH", date=date(2024, 1, 15),
            open=10.0, high=10.5, low=9.8, close=10.2,
            volume=100000, amount=1020000.0,
            pre_close=10.0,
        )
        assert bar.change_pct == pytest.approx(2.0)

    def test_limit_detection(self):
        bar = Bar(
            code="600000.SH", date=date(2024, 1, 15),
            open=11.0, high=11.0, low=11.0, close=11.0,
            volume=100000, amount=1100000.0,
            pre_close=10.0, up_limit=11.0, down_limit=9.0,
        )
        assert bar.is_limit_up is True


class TestSignal:
    def test_valid_signal(self):
        s = Signal(code="600000.SH", side=OrderSide.BUY, quantity=100, reason="测试")
        assert s.quantity == 100

    def test_invalid_quantity(self):
        with pytest.raises(ValueError):
            Signal(code="600000.SH", side=OrderSide.BUY, quantity=50, reason="测试")

    def test_signal_confidence_range(self):
        with pytest.raises(ValueError):
            Signal(code="600000.SH", side=OrderSide.BUY, quantity=100, confidence=1.5)


class TestOrder:
    def test_order_lifecycle(self):
        o = Order(
            order_id="ord_001",
            code="600000.SH",
            side=OrderSide.BUY,
            quantity=1000,
            price=10.0,
            status=OrderStatus.PENDING,
        )
        assert not o.is_finished
        o.status = OrderStatus.FILLED
        assert o.is_finished


class TestEventBus:
    def test_register_and_emit(self):
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.register(EventType.BAR, handler)
        bus.emit(Event(type=EventType.BAR, data={"test": True}))

        assert len(received) == 1
        assert received[0].type == EventType.BAR

    def test_unregister(self):
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.register(EventType.BAR, handler)
        bus.unregister(EventType.BAR, handler)
        bus.emit(Event(type=EventType.BAR, data={}))

        assert len(received) == 0

    def test_multiple_handlers(self):
        bus = EventBus()
        results = []

        def h1(e): results.append("h1")
        def h2(e): results.append("h2")

        bus.register(EventType.BAR, h1)
        bus.register(EventType.BAR, h2)
        bus.emit(Event(type=EventType.BAR, data={}))

        assert len(results) == 2

    def test_handler_exception_does_not_crash(self):
        bus = EventBus()
        results = []

        def bad_handler(e):
            raise RuntimeError("oops")
        def good_handler(e):
            results.append("ok")

        bus.register(EventType.BAR, bad_handler)
        bus.register(EventType.BAR, good_handler)

        # 不应抛出异常
        bus.emit(Event(type=EventType.BAR, data={}))
        assert results == ["ok"]

    def test_stats(self):
        bus = EventBus()
        bus.emit(Event(type=EventType.BAR, data={}))
        bus.emit(Event(type=EventType.BAR, data={}))
        bus.emit(Event(type=EventType.SIGNAL, data={}))

        stats = bus.stats
        assert stats["bar"] == 2
        assert stats["signal"] == 1


class TestPosition:
    def test_position_defaults(self):
        p = Position(code="000001.SZ")
        assert p.quantity == 0
        assert p.available == 0
        assert p.market_value == 0.0
