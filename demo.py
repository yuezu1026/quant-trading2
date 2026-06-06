"""
演示脚本 — 端到端量化回测流程

运行方式:
    cd quant-trading
    python demo.py

流程:
    1. 从 AkShare 下载数据
    2. 运行双均线策略回测
    3. 输出绩效报告
"""
from __future__ import annotations

import logging
from datetime import date

from core.types import Bar
from strategy import StrategyWrapper, MACrossStrategy
from backtest import BacktestEngine, Analyzer
from data import AkShareProvider

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("demo")


def main():
    # 1. 创建数据源
    provider = AkShareProvider()
    logger.info("数据源: AkShare")

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
    codes = ["600036.SH"]  # 招商银行
    start = date(2023, 1, 1)
    end = date(2024, 12, 31)

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
        print(f"  起始资金: ¥{daily_df['total_asset'].iloc[0]:,.2f}")
        print(f"  最终资产: ¥{daily_df['total_asset'].iloc[-1]:,.2f}")
        print(f"  最高资产: ¥{daily_df['total_asset'].max():,.2f}")
        print(f"  最低资产: ¥{daily_df['total_asset'].min():,.2f}")


if __name__ == "__main__":
    main()
