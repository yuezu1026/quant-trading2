"""
数据仓库 — 统一的数据存取接口

上层代码通过 Repository 读写数据，不直接接触 SQL。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session

from .models import Base, DailyKline, StockInfo, TradeRecord, BacktestRun

DAILY_COLUMNS = ["code", "date", "open", "high", "low", "close", "volume", "amount"]


class Repository:
    """数据仓库"""

    def __init__(self, db_url: str = "sqlite:///quant.db"):
        self._engine: Engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # 日K线
    # ------------------------------------------------------------------

    def save_daily(self, df: pd.DataFrame) -> int:
        """批量保存日K线（存在则更新）"""
        if df.empty:
            return 0

        records = []
        for _, row in df.iterrows():
            records.append(DailyKline(
                code=row["code"],
                date=row["date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                amount=row["amount"],
            ))

        with Session(self._engine) as session:
            for r in records:
                existing = session.query(DailyKline).filter_by(
                    code=r.code, date=r.date
                ).first()
                if existing:
                    # 更新
                    for attr in ["open", "high", "low", "close", "volume", "amount"]:
                        setattr(existing, attr, getattr(r, attr))
                else:
                    session.add(r)
            session.commit()

        return len(records)

    def get_daily(
        self,
        code: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """查询日K线数据"""
        with Session(self._engine) as session:
            rows = session.query(DailyKline).filter(
                DailyKline.code == code,
                DailyKline.date >= start,
                DailyKline.date <= end,
            ).order_by(DailyKline.date).all()

        if not rows:
            return pd.DataFrame(columns=DAILY_COLUMNS)

        data = []
        for r in rows:
            data.append({
                "code": r.code,
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "amount": r.amount,
            })
        return pd.DataFrame(data)

    def get_all_codes(self) -> list[str]:
        """获取所有已存储的股票代码"""
        with Session(self._engine) as session:
            rows = session.query(DailyKline.code).distinct().all()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # 股票信息
    # ------------------------------------------------------------------

    def update_stock_info(self, code: str, info: dict) -> None:
        """更新股票基本信息"""
        with Session(self._engine) as session:
            existing = session.query(StockInfo).filter_by(code=code).first()
            if existing:
                for k, v in info.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                session.add(StockInfo(code=code, **info))
            session.commit()

    def get_stock_info(self, code: str) -> Optional[dict]:
        """获取股票信息"""
        with Session(self._engine) as session:
            si = session.query(StockInfo).filter_by(code=code).first()
        if si is None:
            return None
        return {
            "code": si.code,
            "name": si.name,
            "industry": si.industry,
            "area": si.area,
            "market_cap": si.market_cap,
            "circulating_cap": si.circulating_cap,
            "listed_date": si.listed_date,
            "is_st": si.is_st,
        }

    # ------------------------------------------------------------------
    # 交易记录
    # ------------------------------------------------------------------

    def save_trade(self, record: dict) -> None:
        """保存一笔交易记录"""
        with Session(self._engine) as session:
            session.add(TradeRecord(**record))
            session.commit()

    def get_trades(
        self,
        strategy_name: Optional[str] = None,
        run_mode: Optional[str] = None,
    ) -> pd.DataFrame:
        """查询交易记录"""
        with Session(self._engine) as session:
            q = session.query(TradeRecord)
            if strategy_name:
                q = q.filter(TradeRecord.strategy_name == strategy_name)
            if run_mode:
                q = q.filter(TradeRecord.run_mode == run_mode)
            rows = q.order_by(TradeRecord.trade_time).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame([{
            "strategy_name": r.strategy_name,
            "run_mode": r.run_mode,
            "code": r.code,
            "side": r.side,
            "quantity": r.quantity,
            "price": r.price,
            "commission": r.commission,
            "tax": r.tax,
            "pnl": r.pnl,
            "trade_time": r.trade_time,
            "signal_reason": r.signal_reason,
        } for r in rows])

    # ------------------------------------------------------------------
    # 回测结果
    # ------------------------------------------------------------------

    def save_backtest(self, data: dict) -> int:
        """保存回测结果，返回记录ID"""
        with Session(self._engine) as session:
            run = BacktestRun(**data)
            session.add(run)
            session.commit()
            return run.id

    def get_latest_backtests(self, limit: int = 5) -> list[dict]:
        """获取最近的回测结果"""
        with Session(self._engine) as session:
            rows = session.query(BacktestRun).order_by(
                BacktestRun.created_at.desc()
            ).limit(limit).all()
        return [{
            "id": r.id,
            "strategy_name": r.strategy_name,
            "codes": r.codes,
            "start_date": str(r.start_date),
            "end_date": str(r.end_date),
            "total_return": r.total_return,
            "annual_return": r.annual_return,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "volatility": r.volatility,
            "trade_count": r.trade_count,
            "win_rate": r.win_rate,
            "equity_curve": r.equity_curve,
            "created_at": str(r.created_at),
        } for r in rows]
