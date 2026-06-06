"""
AkShare 数据源适配器

免费开源的 A股数据接口，覆盖历史日K线、分钟线、股票列表等。
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from .base import DataProvider, DAILY_COLUMNS

logger = logging.getLogger(__name__)


def _normalize_code(code: str) -> str:
    """
    标准化股票代码。

    输入可能: 600000.SH, 600000, sh600000, 600000.XSHG
    统一输出: "600000" (纯数字, AkShare 格式)
    """
    code = code.replace(".SH", "").replace(".SZ", "").replace(".XSHG", "").replace(".XSHE", "")
    code = code.replace("sh", "").replace("sz", "").replace("SH", "").replace("SZ", "")
    return code.zfill(6)


def _code_to_ak_symbol(code: str) -> str:
    """
    转为 AkShare 需要的 symbol 格式。
    沪市: sh600000, 深市: sz000001
    """
    pure = _normalize_code(code)
    if pure.startswith(("6", "5", "9")):
        return f"sh{pure}"
    else:
        return f"sz{pure}"


def _code_to_stored(code: str) -> str:
    """
    转为标准存储格式。
    沪市: 600000.SH, 深市: 000001.SZ
    """
    pure = _normalize_code(code)
    if pure.startswith(("6", "5", "9")):
        return f"{pure}.SH"
    else:
        return f"{pure}.SZ"


class AkShareProvider(DataProvider):
    """AkShare 数据源"""

    name = "akshare"

    # ------------------------------------------------------------------
    # 日K线
    # ------------------------------------------------------------------

    def get_daily(
        self,
        code: str,
        start: date,
        end: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        import akshare as ak

        symbol = _code_to_ak_symbol(code)
        stored = _code_to_stored(code)

        # 映射复权参数
        ak_adjust = {"qfq": "qfq", "hfq": "hfq", "none": ""}[adjust]

        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=ak_adjust,
        )

        if df.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)

        # 统一列名
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        })

        df["code"] = stored
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[DAILY_COLUMNS]
        df = df.sort_values("date").reset_index(drop=True)

        return df

    # ------------------------------------------------------------------
    # 分钟K线
    # ------------------------------------------------------------------

    def get_minute(
        self,
        code: str,
        date_: date,
        freq: str = "1",
    ) -> pd.DataFrame:
        import akshare as ak

        symbol = _code_to_ak_symbol(code)
        stored = _code_to_stored(code)

        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol,
            period=freq,
            start_date=date_.strftime("%Y-%m-%d"),
            end_date=date_.strftime("%Y-%m-%d"),
            adjust="",
        )

        if df.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS + ["time"])

        # 统一列名 (AkShare分钟线列名可能不同，适配一下)
        rename_map = {}
        for col in df.columns:
            if "时间" in col:
                rename_map[col] = "time"
            elif "开盘" in col:
                rename_map[col] = "open"
            elif "收盘" in col:
                rename_map[col] = "close"
            elif "最高" in col:
                rename_map[col] = "high"
            elif "最低" in col:
                rename_map[col] = "low"
            elif "成交量" in col:
                rename_map[col] = "volume"
            elif "成交额" in col:
                rename_map[col] = "amount"
        df = df.rename(columns=rename_map)

        df["code"] = stored
        df["date"] = date_
        cols = [c for c in DAILY_COLUMNS + ["time"] if c in df.columns]
        return df[cols]

    # ------------------------------------------------------------------
    # 股票信息
    # ------------------------------------------------------------------

    def get_stock_info(self, code: str) -> dict:
        import akshare as ak

        pure = _normalize_code(code)
        try:
            df = ak.stock_individual_info_em(symbol=pure)
            info = {}
            for _, row in df.iterrows():
                info[row["item"]] = row["value"]
            return info
        except Exception:
            logger.exception(f"获取股票信息失败: {code}")
            return {"code": _code_to_stored(code)}

    def get_stock_list(self) -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        df = df.rename(columns={
            "代码": "code",
            "名称": "name",
            "最新价": "price",
        })

        df["code"] = df["code"].apply(
            lambda x: f"{x}.SH" if str(x).startswith(("6", "5", "9")) else f"{x}.SZ"
        )
        return df[["code", "name", "price"]]
