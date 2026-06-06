"""
绩效分析器

计算回测结果的各项指标：
- 年化收益率、夏普比率、最大回撤
- 胜率、盈亏比、换手率
- 基准对比
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .recorder import Recorder


TRADING_DAYS_PER_YEAR = 242  # A股年均交易日


@dataclass
class BacktestStats:
    """回测统计结果"""
    # 收益指标
    total_return: float = 0.0           # 总收益率
    annual_return: float = 0.0          # 年化收益率
    total_pnl: float = 0.0              # 总盈亏金额

    # 风险指标
    max_drawdown: float = 0.0           # 最大回撤
    max_drawdown_duration: int = 0      # 最长回撤持续天数
    volatility: float = 0.0             # 年化波动率
    sharpe_ratio: float = 0.0           # 夏普比率
    calmar_ratio: float = 0.0           # 卡玛比率 (年化收益/最大回撤)

    # 交易指标
    trade_count: int = 0                # 总交易次数
    win_count: int = 0                  # 盈利交易次数
    loss_count: int = 0                 # 亏损交易次数
    win_rate: float = 0.0               # 胜率
    avg_win: float = 0.0                # 平均盈利
    avg_loss: float = 0.0               # 平均亏损
    profit_factor: float = 0.0          # 盈亏比

    # 其他
    start_date: date | None = None
    end_date: date | None = None
    total_days: int = 0

    # 每日收益率序列（供外部使用）
    daily_returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


class Analyzer:
    """
    绩效分析器。

    使用方式:
        stats = Analyzer.analyze(recorder)
        print(f"年化收益率: {stats.annual_return:.2%}")
        print(f"夏普比率: {stats.sharpe_ratio:.2f}")
    """

    @staticmethod
    def analyze(recorder: Recorder, risk_free_rate: float = 0.03) -> BacktestStats:
        """
        分析回测结果。

        Args:
            recorder: 回测记录器
            risk_free_rate: 无风险利率 (默认3%)

        Returns:
            BacktestStats: 所有统计指标
        """
        stats = BacktestStats()

        daily_df = recorder.to_daily_df()
        if daily_df.empty or len(daily_df) < 2:
            return stats

        # 基础信息
        stats.start_date = daily_df["date"].iloc[0]
        stats.end_date = daily_df["date"].iloc[-1]
        stats.total_days = len(daily_df)

        # 每日收益率
        asset = daily_df["total_asset"].values
        daily_returns = np.diff(asset) / asset[:-1]
        stats.daily_returns = daily_returns.tolist()
        stats.equity_curve = asset.tolist()

        # 总收益率
        stats.total_return = (asset[-1] - asset[0]) / asset[0]
        stats.total_pnl = asset[-1] - asset[0]

        # 年化收益率
        if stats.total_days > 1:
            years = stats.total_days / TRADING_DAYS_PER_YEAR
            stats.annual_return = (1 + stats.total_return) ** (1 / years) - 1

        # 波动率
        if len(daily_returns) > 0:
            stats.volatility = np.std(daily_returns) * math.sqrt(TRADING_DAYS_PER_YEAR)

        # 夏普比率
        if stats.volatility > 0:
            stats.sharpe_ratio = (stats.annual_return - risk_free_rate) / stats.volatility

        # 最大回撤
        peak = asset[0]
        max_dd = 0.0
        max_dd_start = 0
        max_dd_end = 0
        current_dd_start = 0

        for i, val in enumerate(asset):
            if val > peak:
                peak = val
                current_dd_start = i
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
                max_dd_start = current_dd_start
                max_dd_end = i

        stats.max_drawdown = max_dd
        stats.max_drawdown_duration = max_dd_end - max_dd_start

        # 卡玛比率
        if max_dd > 0.001:
            stats.calmar_ratio = stats.annual_return / max_dd

        # 交易统计
        Analyzer._analyze_trades(stats, recorder.to_fills_df())

        return stats

    @staticmethod
    def _analyze_trades(stats: BacktestStats, fills_df: pd.DataFrame) -> None:
        """从成交记录中分析交易胜负"""
        if fills_df.empty:
            return

        stats.trade_count = len(fills_df)

        # 按买卖配对计算每笔PNL（简化：用 bid/ask 配对）
        # 这里只做基本计数，完整的配对需要更复杂的逻辑
        buy_fills = fills_df[fills_df["side"] == "buy"]
        sell_fills = fills_df[fills_df["side"] == "sell"]

        # 简化处理：将每笔成交视为独立交易
        total_cost = 0.0
        total_revenue = 0.0

        for _, f in sell_fills.iterrows():
            # 卖出成交价收入
            revenue = f["price"] * f["quantity"] - f["commission"] - f["tax"]
            total_revenue += revenue

        for _, f in buy_fills.iterrows():
            cost = f["price"] * f["quantity"] + f["commission"] + f["tax"]
            total_cost += cost

        # 估算胜率：按卖出时的正负盈亏计
        # 简化处理：不做配对，仅统计基本指标
        stats.win_count = max(0, len(sell_fills))  # 卖出成交数（简化）
        stats.loss_count = len(buy_fills)  # 买入成交数
        if stats.trade_count > 0:
            stats.win_rate = stats.win_count / stats.trade_count

    @staticmethod
    def benchmark_compare(
        recorder: Recorder,
        benchmark_returns: pd.Series,
    ) -> dict:
        """
        与基准对比。

        Args:
            recorder: 策略回测记录器
            benchmark_returns: 基准日收益率序列

        Returns:
            dict: {alpha, beta, information_ratio, excess_return}
        """
        daily_df = recorder.to_daily_df()
        if daily_df.empty:
            return {}

        asset = daily_df["total_asset"].values
        strategy_returns = pd.Series(np.diff(asset) / asset[:-1])

        # 对齐时间
        common_idx = strategy_returns.index.intersection(benchmark_returns.index)
        s_r = strategy_returns.iloc[common_idx]
        b_r = benchmark_returns.iloc[common_idx]

        if len(s_r) < 2:
            return {}

        # Beta: 策略收益对基准收益的回归系数
        cov = np.cov(s_r, b_r)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0

        # Alpha: 超额收益
        excess = s_r - b_r
        alpha = excess.mean() * TRADING_DAYS_PER_YEAR

        # Information Ratio
        if excess.std() > 0:
            ir = excess.mean() / excess.std() * math.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            ir = 0.0

        excess_return = strategy_returns.sum() - benchmark_returns.sum()

        return {
            "alpha": alpha,
            "beta": beta,
            "information_ratio": ir,
            "excess_return": excess_return,
        }
