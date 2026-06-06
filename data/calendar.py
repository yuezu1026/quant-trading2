"""
A股交易日历

提供交易日判断、日期范围生成等功能。
基于 AkShare 的交易日历数据。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class TradingCalendar:
    """
    A股交易日历。

    特性:
    - 缓存交易日列表，避免重复请求
    - 支持判断某日是否为交易日
    - 支持获取前后N个交易日
    """

    def __init__(self):
        self._calendar: Optional[set[date]] = None
        self._year_range: tuple[int, int] = (2000, 2030)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def load(self, start_year: int = 2000, end_year: int = 2030) -> None:
        """
        从 AkShare 加载交易日历。

        如果 AkShare 不可用，使用备用的简单估算（剔除周末）。
        """
        try:
            import akshare as ak

            dfs = []
            for year in range(start_year, end_year + 1):
                try:
                    df = ak.tool_trade_date_hist_sina()
                    dfs.append(df)
                except Exception:
                    # 单年失败不影响整体
                    logger.warning(f"加载 {year} 交易日历失败，跳过")

            if dfs:
                all_dates = pd.concat(dfs)
                all_dates["trade_date"] = pd.to_datetime(all_dates["trade_date"])
                self._calendar = set(
                    d.date() for d in all_dates["trade_date"]
                )
                self._year_range = (start_year, end_year)
                logger.info(f"交易日历加载成功，共 {len(self._calendar)} 个交易日")
            else:
                raise RuntimeError("没有加载到任何交易日历数据")

        except (ImportError, Exception) as e:
            logger.warning(f"AkShare交易日历加载失败({e})，使用备用估算")
            self._load_fallback(start_year, end_year)

    def _load_fallback(self, start_year: int, end_year: int) -> None:
        """
        备用方案：用所有非周末日期近似交易日历。
        注意：这会漏掉法定节假日，只作为开发时的近似替代。
        """
        dates = set()
        current = date(start_year, 1, 1)
        end = date(end_year, 12, 31)

        while current <= end:
            if current.weekday() < 5:  # 周一到周五
                dates.add(current)
            current += timedelta(days=1)

        self._calendar = dates
        self._year_range = (start_year, end_year)
        logger.warning(
            f"备用交易日历: {len(dates)}天 (含法定节假日, 仅剔除周末)"
        )

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._calendar is not None

    def ensure_loaded(self) -> None:
        if not self.is_loaded:
            self.load()

    def is_trading_day(self, d: date | datetime) -> bool:
        """判断某日是否为交易日"""
        self.ensure_loaded()
        if isinstance(d, datetime):
            d = d.date()
        return d in self._calendar

    def next_trading_day(self, d: date | datetime, n: int = 1) -> date:
        """获取之后第 n 个交易日"""
        self.ensure_loaded()
        if isinstance(d, datetime):
            d = d.date()
        current = d + timedelta(days=1)
        found = 0
        while True:
            if current in self._calendar:
                found += 1
                if found == n:
                    return current
            current += timedelta(days=1)

    def prev_trading_day(self, d: date | datetime, n: int = 1) -> date:
        """获取之前第 n 个交易日"""
        self.ensure_loaded()
        if isinstance(d, datetime):
            d = d.date()
        current = d - timedelta(days=1)
        found = 0
        while True:
            if current in self._calendar:
                found += 1
                if found == n:
                    return current
            current -= timedelta(days=1)

    def trading_days(self, start: date, end: date) -> list[date]:
        """获取日期范围内的所有交易日"""
        self.ensure_loaded()
        days = []
        current = start
        while current <= end:
            if current in self._calendar:
                days.append(current)
            current += timedelta(days=1)
        return days

    @property
    def all_dates(self) -> list[date]:
        """返回所有已缓存的交易日（排序）"""
        self.ensure_loaded()
        return sorted(self._calendar)
