"""
TuShare 数据源适配器

替代 AkShare，提供更稳定的A股数据接口。
需要配置 TUSHARE_TOKEN 环境变量或在 config/settings.yaml 中设置 token。

前置条件:
    pip install tushare
    在 https://tushare.pro 注册获取 token
"""
from __future__ import annotations

import logging
import os
from datetime import date

import pandas as pd

from .base import DataProvider, DAILY_COLUMNS

logger = logging.getLogger(__name__)


def _get_token() -> str:
    """获取 TuShare token — 优先环境变量，其次配置文件"""
    token = os.environ.get("TUSHARE_TOKEN", "")
    if token:
        return token
    # 尝试从配置文件读取 (优先 local 覆盖)
    try:
        import yaml
        base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        base_dir = os.path.normpath(base_dir)

        # 先读主配置
        token = ""
        for cfg_name in ["settings.yaml", "settings.local.yaml"]:
            cfg_path = os.path.join(base_dir, cfg_name)
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                t = cfg.get("data", {}).get("tushare_token", "")
                if t:
                    token = t  # local 覆盖主配置
    except Exception:
        pass
    return token


def _get_pro():
    """获取 TuShare Pro API 实例"""
    import tushare as ts

    token = _get_token()
    if not token:
        raise RuntimeError(
            "未配置 TuShare token。请在环境变量 TUSHARE_TOKEN 中设置，"
            "或在 config/settings.yaml 的 data.tushare_token 中配置。\n"
            "获取 token: https://tushare.pro"
        )
    ts.set_token(token)
    return ts.pro_api()


# ------------------------------------------------------------------
# 代码格式转换
# ------------------------------------------------------------------

def _normalize_code(code: str) -> str:
    """标准化代码: '600000.SH', '600000', 'sh600000' -> '600000.SH'"""
    code = code.strip().upper()
    # 已有后缀
    if code.endswith(".SH") or code.endswith(".SZ"):
        return code
    # 带前缀
    if code.startswith("SH"):
        return code[2:] + ".SH"
    if code.startswith("SZ"):
        return code[2:] + ".SZ"
    # 纯数字
    code = code.zfill(6)
    if code.startswith(("6", "5", "9")):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"


def _code_to_ts(code: str) -> str:
    """转为 TuShare ts_code 格式: 600000.SH / 000001.SZ"""
    return _normalize_code(code)


# ------------------------------------------------------------------
# TuShare Provider
# ------------------------------------------------------------------

# 全局调用记录
_call_count: int = 0
_call_log: list[dict] = []  # {endpoint, uri, time}


def get_call_count() -> int:
    return _call_count


def get_call_log(limit: int = 10) -> list[dict]:
    return _call_log[-limit:]


def _record_call(endpoint: str, uri: str = "") -> None:
    global _call_count
    _call_count += 1
    from datetime import datetime
    _call_log.append({
        "endpoint": endpoint,
        "uri": uri,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    if len(_call_log) > 200:
        _call_log[:] = _call_log[-200:]


class TuShareProvider(DataProvider):
    """TuShare 数据源适配器"""

    name = "tushare"

    def __init__(self, token: str = ""):
        self._token = token or _get_token()
        self._pro = None

    @property
    def pro(self):
        """延迟初始化 pro API"""
        global _call_count
        _call_count += 1
        if self._pro is None:
            import tushare as ts

            if not self._token:
                raise RuntimeError("未配置 TuShare token")
            ts.set_token(self._token)
            self._pro = ts.pro_api()
        return self._pro

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
        ts_code = _code_to_ts(code)

        # TuShare 复权参数: qfq/hfq/None
        if adjust == "qfq":
            adj_param = "qfq"
        elif adjust == "hfq":
            adj_param = "hfq"
        else:
            adj_param = None

        try:
            if adj_param:
                # 使用复权接口
                _record_call("daily", f"ts_code={ts_code}&start={start}&end={end}")
                df = self.pro.query(
                    "daily",
                    ts_code=ts_code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
                # 复权因子
                _record_call("adj_factor", f"ts_code={ts_code}")
                adj_df = self.pro.adj_factor(
                    ts_code=ts_code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
                if not adj_df.empty and not df.empty:
                    adj_df = adj_df[["trade_date", "adj_factor"]]
                    df = df.merge(adj_df, on="trade_date", how="left")
                    latest_factor = adj_df["adj_factor"].iloc[-1] if not adj_df.empty else 1.0
                    if adj_param == "qfq" and "adj_factor" in df.columns:
                        for col in ["open", "high", "low", "close"]:
                            df[col] = df[col] * df["adj_factor"] / latest_factor
                    elif adj_param == "hfq" and "adj_factor" in df.columns:
                        for col in ["open", "high", "low", "close"]:
                            df[col] = df[col] * df["adj_factor"]
            else:
                _record_call("daily", f"ts_code={ts_code}&start={start}&end={end}")
                df = self.pro.daily(
                    ts_code=ts_code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
        except Exception:
            logger.exception(f"TuShare 获取日线失败: {ts_code}")
            return pd.DataFrame(columns=DAILY_COLUMNS)

        if df.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)

        # 统一列名
        df = df.rename(columns={
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
        })

        df["code"] = ts_code
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)

        # 只保留标准列
        cols = [c for c in DAILY_COLUMNS if c in df.columns]
        return df[cols]

    # ------------------------------------------------------------------
    # 分钟K线
    # ------------------------------------------------------------------

    def get_minute(
        self,
        code: str,
        date_: date,
        freq: str = "1",
    ) -> pd.DataFrame:
        ts_code = _code_to_ts(code)

        try:
            _record_call("mins", f"ts_code={ts_code}&freq={freq}min&date={date_}")
            df = self.pro.mins(
                ts_code=ts_code,
                freq=f"{freq}min",
                start_date=date_.strftime("%Y-%m-%d 09:30:00"),
                end_date=date_.strftime("%Y-%m-%d 15:00:00"),
            )
        except Exception:
            logger.exception(f"TuShare 获取分钟线失败: {ts_code}")
            return pd.DataFrame(columns=DAILY_COLUMNS + ["time"])

        if df.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS + ["time"])

        df = df.rename(columns={
            "ts_code": "code",
            "trade_time": "time",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
        })

        df["date"] = date_
        cols = [c for c in DAILY_COLUMNS + ["time"] if c in df.columns]
        return df[cols]

    # ------------------------------------------------------------------
    # 股票信息
    # ------------------------------------------------------------------

    def get_stock_info(self, code: str) -> dict:
        ts_code = _code_to_ts(code)
        try:
            _record_call("stock_basic", f"ts_code={ts_code}")
            df = self.pro.stock_basic(
                ts_code=ts_code,
                fields="ts_code,name,area,industry,list_date",
            )
            if not df.empty:
                row = df.iloc[0].to_dict()
                return {
                    "code": ts_code,
                    "name": row.get("name", ""),
                    "area": row.get("area", ""),
                    "industry": row.get("industry", ""),
                    "list_date": row.get("list_date", ""),
                }
        except Exception:
            logger.exception(f"TuShare 获取股票信息失败: {ts_code}")
        return {"code": ts_code}

    def get_stock_list(self) -> pd.DataFrame:
        try:
            _record_call("stock_basic", "exchange=&list_status=L")
            df = self.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,list_date",
            )
            if df.empty:
                return pd.DataFrame(columns=["code", "name"])
            df = df.rename(columns={"ts_code": "code"})
            return df[["code", "name"]]
        except Exception:
            logger.exception("TuShare 获取股票列表失败")
            return pd.DataFrame(columns=["code", "name"])
