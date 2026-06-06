"""
回测引擎 — 事件驱动的核心循环

流程:
1. 加载历史数据，按时间顺序遍历
2. 每个 Bar 通知策略 → 策略返回信号
3. 信号转为订单 → 提交到模拟券商
4. 券商撮合 → 更新账户
5. 记录结果 → 收盘结算

同一套引擎逻辑可复用于模拟交易和实盘交易（替换券商和数据源）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import pandas as pd

from core.types import (
    Bar, Order, OrderType, OrderStatus,
    Event, EventType, Account, Signal,
)
from core.event_bus import EventBus
from data import Repository, DataProvider, TradingCalendar
from strategy.base import StrategyWrapper
from .broker import SimulatedBroker
from .recorder import Recorder

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    事件驱动回测引擎。

    使用方式:
        engine = BacktestEngine(
            strategy=my_strategy,
            data_provider=provider,
            initial_cash=100000,
        )
        result = engine.run(codes=["600000.SH"], start=date(2020,1,1), end=date(2024,12,31))
        print(result.stats)
    """

    def __init__(
        self,
        strategy: StrategyWrapper,
        data_provider: DataProvider,
        initial_cash: float = 100_000.0,
        commission_rate: float = 0.00025,
        stamp_tax_rate: float = 0.001,
    ):
        self._strategy = strategy
        self._data_provider = data_provider
        self._broker = SimulatedBroker(initial_cash)
        self._recorder = Recorder()
        self._event_bus = EventBus()
        self._calendar = TradingCalendar()

        # 配置
        self._commission_rate = commission_rate
        self._stamp_tax_rate = stamp_tax_rate

        # 运行时状态
        self._is_running = False
        self._current_bar: Optional[Bar] = None

        # 注册内部处理器
        self._event_bus.register(EventType.SIGNAL, self._on_signal)
        self._event_bus.register(EventType.FILL, self._on_fill)
        self._event_bus.register(EventType.ORDER, self._on_order)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(
        self,
        codes: list[str],
        start: date,
        end: date,
    ) -> Recorder:
        """
        运行回测。

        Args:
            codes: 股票代码列表
            start: 回测起始日
            end: 回测结束日

        Returns:
            Recorder: 包含所有回测结果的记录器
        """
        self.reset()

        # 获取交易日列表
        trading_days = self._get_trading_days(start, end)
        logger.info(
            f"回测开始: {start} ~ {end}, "
            f"{len(codes)} 只股票, {len(trading_days)} 个交易日"
        )

        self._strategy.on_start()

        # 预加载所有股票数据
        all_data = self._load_data(codes, start, end)
        if all_data.empty:
            logger.error("没有加载到任何数据")
            return self._recorder

        # 按交易日遍历
        for day in trading_days:
            day_data = all_data[all_data["date"] == day]
            if day_data.empty:
                continue

            for _, row in day_data.iterrows():
                bar = Bar(
                    code=row["code"],
                    date=row["date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    amount=row["amount"],
                    pre_close=row.get("pre_close", None),
                )

                # 计算涨跌停价
                if bar.pre_close and bar.pre_close > 0:
                    bar.up_limit = round(bar.pre_close * 1.10, 2)
                    bar.down_limit = round(bar.pre_close * 0.90, 2)

                self._current_bar = bar

                # Step 1: 撮合已有订单
                fills = self._broker.match(bar)
                for fill in fills:
                    self._event_bus.emit(Event(type=EventType.FILL, data=fill))

                # Step 2: 通知策略
                try:
                    signals = self._strategy.on_bar(bar, self._broker.account)
                except Exception:
                    logger.exception(f"策略异常: {bar.code} {bar.date}")
                    continue

                # Step 3: 处理信号
                for signal in signals:
                    self._event_bus.emit(Event(type=EventType.SIGNAL, data=signal))

            # 收盘结算
            for code in codes:
                code_bar = day_data[day_data["code"] == code]
                if not code_bar.empty:
                    row = code_bar.iloc[0]
                    self._broker.end_of_day(Bar(**{
                        "code": row["code"],
                        "date": row["date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                        "amount": row["amount"],
                    }))

            # 每日记录
            self._recorder.record_daily(day, self._broker.account)

        self._strategy.on_stop()
        logger.info(f"回测完成: 总收益率 {self._recorder.total_return:.2%}")

        return self._recorder

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_signal(self, event: Event) -> None:
        """处理策略信号 → 创建订单"""
        signal: Signal = event.data
        order = Order(
            order_id=f"ord_{uuid.uuid4().hex[:8]}",
            code=signal.code,
            side=signal.side,
            quantity=signal.quantity,
            price=signal.price or self._current_bar.close if self._current_bar else 0,
            order_type=signal.order_type,
            status=OrderStatus.PENDING,
            signal=signal,
        )
        self._broker.submit_order(order)
        self._recorder.record_order(order)

    def _on_fill(self, event: Event) -> None:
        """处理成交 → 记录 & 通知策略"""
        fill = event.data
        self._recorder.record_fill(fill)
        try:
            self._strategy.on_fill(fill, self._broker.account)
        except Exception:
            logger.exception(f"策略 on_fill 异常: {fill.fill_id}")

    def _on_order(self, event: Event) -> None:
        """处理订单更新"""
        pass  # 预留扩展

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _load_data(self, codes: list[str], start: date, end: date) -> pd.DataFrame:
        """加载所有股票的历史数据"""
        frames = []
        for code in codes:
            try:
                df = self._data_provider.get_daily(code, start, end)
                if not df.empty:
                    frames.append(df)
            except Exception:
                logger.exception(f"加载数据失败: {code}")
        if frames:
            result = pd.concat(frames, ignore_index=True)
            logger.info(f"数据加载完成: {result.shape[0]} 行")
            return result
        return pd.DataFrame()

    def _get_trading_days(self, start: date, end: date) -> list[date]:
        """获取交易日列表"""
        self._calendar.ensure_loaded()
        return self._calendar.trading_days(start, end)

    def reset(self) -> None:
        """重置引擎状态"""
        self._broker.reset()
        self._recorder.reset()
        self._is_running = False
        self._current_bar = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def account(self) -> Account:
        return self._broker.account

    @property
    def broker(self) -> SimulatedBroker:
        return self._broker

    @property
    def recorder(self) -> Recorder:
        return self._recorder
