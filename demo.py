"""
演示脚本 — 端到端量化回测流程

运行方式:
    cd quant-trading
    python demo.py

流程:
    1. 尝试从 AkShare 下载数据，失败则使用模拟数据
    2. 运行双均线策略回测
    3. 输出绩效报告
"""
from __future__ import annotations

import logging
import random
from datetime import date, timedelta

import pandas as pd

from core.types import Bar
from strategy import StrategyWrapper, MACrossStrategy
from backtest import BacktestEngine, Analyzer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("demo")


def generate_mock_data(
    codes: list[str],
    start: date,
    end: date,
    seed: int = 42,
) -> pd.DataFrame:
    """
    生成模拟K线数据（用于离线测试）。

    以基础价格开始，每个交易日随机波动，模拟真实走势。
    """
    from data import TradingCalendar

    rng = random.Random(seed)
    calendar = TradingCalendar()
    calendar.ensure_loaded()
    trading_days = calendar.trading_days(start, end)

    if not trading_days:
        # 备用：用工作日近似
        current = start
        while current <= end:
            if current.weekday() < 5:
                trading_days.append(current)
            current += timedelta(days=1)

    base_prices = {
        "600036.SH": 35.0,   # 招商银行
        "000001.SZ": 12.0,   # 平安银行
        "600519.SH": 1800.0, # 贵州茅台
    }

    rows = []
    for code in codes:
        price = base_prices.get(code, 20.0)
        for i, dt in enumerate(trading_days):
            # 随机游走 + 趋势
            trend = 0.0002  # 微涨趋势
            change = rng.gauss(trend, 0.02)
            close = price * (1 + change)
            close = max(close, price * 0.5)  # 防止跌到零

            open_p = price * (1 + rng.gauss(0, 0.005))
            high = max(open_p, close) * (1 + abs(rng.gauss(0, 0.008)))
            low = min(open_p, close) * (1 - abs(rng.gauss(0, 0.008)))
            volume = int(abs(rng.gauss(50_000_000, 20_000_000)))
            amount = close * volume

            rows.append({
                "code": code,
                "date": dt,
                "open": round(open_p, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
                "amount": amount,
            })

            price = close  # 下一天的起始价

    logger.info(f"生成模拟数据: {len(rows)} 行, {len(codes)} 只股票")
    return pd.DataFrame(rows)


class MockDataProvider:
    """模拟数据源（离线回退）"""

    name = "mock"

    def __init__(self, df: pd.DataFrame):
        self._df = df

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


def main():
    codes = ["600036.SH"]  # 招商银行
    start = date(2023, 1, 1)
    end = date(2024, 12, 31)

    # 1. 尝试 AkShare，失败则用模拟数据
    try:
        from data import AkShareProvider
        provider = AkShareProvider()
        logger.info("数据源: AkShare (在线)")
        # 快速测试连接
        test_df = provider.get_daily(codes[0], start, start + timedelta(days=5))
        if test_df.empty:
            raise RuntimeError("AkShare 返回空数据")
    except Exception as e:
        logger.warning(f"AkShare 不可用 ({e})，切换为模拟数据")
        mock_df = generate_mock_data(codes, start, end)
        provider = MockDataProvider(mock_df)
        logger.info("数据源: Mock (离线模拟)")

    # 2. 创建策略
    strategy = MACrossStrategy(
        fast_period=5,
        slow_period=20,
        fixed_quantity=0,  # 0=自动计算
    )
    wrapper = StrategyWrapper(strategy)
    logger.info(f"策略: {wrapper.name}")

    # 3. 创建回测引擎
    engine = BacktestEngine(
        strategy=wrapper,
        data_provider=provider,
        initial_cash=100_000.0,
    )

    # 4. 运行回测
    logger.info(f"回测: {codes}, {start} ~ {end}")
    recorder = engine.run(codes=codes, start=start, end=end)

    # 5. 绩效分析
    stats = Analyzer.analyze(recorder)

    print("\n" + "=" * 60)
    print("  回测结果")
    print("=" * 60)
    print(f"  回测区间: {stats.start_date} ~ {stats.end_date}")
    print(f"  交易日数: {stats.total_days}")
    print(f"  总收益率: {stats.total_return:>8.2%}")
    print(f"  年化收益: {stats.annual_return:>8.2%}")
    print(f"  夏普比率: {stats.sharpe_ratio:>8.2f}")
    print(f"  最大回撤: {stats.max_drawdown:>8.2%}")
    print(f"  卡玛比率: {stats.calmar_ratio:>8.2f}")
    print(f"  年化波动: {stats.volatility:>8.2%}")
    print(f"  交易次数: {stats.trade_count:>8d}")
    print(f"  胜    率: {stats.win_rate:>8.2%}")
    print("=" * 60)

    # 6. 显示最近成交
    fills_df = recorder.to_fills_df()
    if not fills_df.empty:
        print(f"\n最近5笔成交:")
        print(fills_df.tail(5).to_string(index=False))

    # 7. 资产曲线摘要
    daily_df = recorder.to_daily_df()
    if not daily_df.empty:
        print(f"\n资产曲线:")
        print(f"  起始资金: Y{daily_df['total_asset'].iloc[0]:,.2f}")
        print(f"  最终资产: Y{daily_df['total_asset'].iloc[-1]:,.2f}")
        print(f"  最高资产: Y{daily_df['total_asset'].max():,.2f}")
        print(f"  最低资产: Y{daily_df['total_asset'].min():,.2f}")


if __name__ == "__main__":
    main()
