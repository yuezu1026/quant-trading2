"""
数据源适配器基类

所有数据源（AkShare、Efinance、Wind等）需实现此接口。
统一输出 pandas DataFrame，列名标准化。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


# 标准日K线列名
DAILY_COLUMNS = ["code", "date", "open", "high", "low", "close", "volume", "amount"]


class DataProvider(ABC):
    """数据源抽象基类"""

    name: str = "base"

    @abstractmethod
    def get_daily(
        self,
        code: str,
        start: date,
        end: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取日K线数据。

        Args:
            code: 股票代码，如 600000.SH
            start: 起始日
            end: 结束日
            adjust: 复权方式 — qfq(前复权) / hfq(后复权) / none(不复权)

        Returns:
            DataFrame, 列: [code, date, open, high, low, close, volume, amount]
        """
        ...

    @abstractmethod
    def get_minute(
        self,
        code: str,
        date_: date,
        freq: str = "1",
    ) -> pd.DataFrame:
        """
        获取分钟K线数据。

        Args:
            code: 股票代码
            date_: 日期
            freq: 频率 — 1/5/15/30/60

        Returns:
            DataFrame, 列同日线 + [time]
        """
        ...

    @abstractmethod
    def get_stock_info(self, code: str) -> dict:
        """获取股票基本信息"""
        ...

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """获取A股全量股票列表"""
        ...
