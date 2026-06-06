"""
SQLAlchemy 数据模型

表示数据库中的表结构。表名统一使用 quant_ 前缀。
"""
from __future__ import annotations


from sqlalchemy import (
    Column,
    String,
    Date,
    Float,
    BigInteger,
    Integer,
    Boolean,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class DailyKline(Base):
    """日K线表"""
    __tablename__ = "quant_daily_kline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(12), nullable=False, comment="股票代码 如 600000.SH")
    date = Column(Date, nullable=False, comment="交易日期")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, comment="成交量(股)")
    amount = Column(Float, nullable=False, comment="成交额(元)")

    __table_args__ = (
        UniqueConstraint("code", "date", name="uq_code_date"),
        Index("idx_code", "code"),
        Index("idx_date", "date"),
    )


class MinuteKline(Base):
    """分钟K线表"""
    __tablename__ = "quant_minute_kline"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(12), nullable=False)
    date = Column(Date, nullable=False)
    time = Column(String(10), nullable=False, comment="时间 HH:MM")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("code", "date", "time", name="uq_code_date_time_min"),
        Index("idx_min_code", "code"),
        Index("idx_min_date", "date"),
    )


class StockInfo(Base):
    """股票基本信息"""
    __tablename__ = "quant_stock_info"

    code = Column(String(12), primary_key=True, comment="股票代码")
    name = Column(String(20), nullable=False, comment="股票名称")
    industry = Column(String(50), default="", comment="行业")
    area = Column(String(20), default="", comment="地区")
    market_cap = Column(Float, default=0.0, comment="总市值")
    circulating_cap = Column(Float, default=0.0, comment="流通市值")
    listed_date = Column(Date, nullable=True, comment="上市日期")
    is_st = Column(Boolean, default=False, comment="是否ST")


class TradeRecord(Base):
    """交易记录（回测/实盘共用）"""
    __tablename__ = "quant_trade_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(50), nullable=False, comment="策略名称")
    run_mode = Column(String(10), nullable=False, comment="backtest/paper/live")
    code = Column(String(12), nullable=False)
    side = Column(String(5), nullable=False, comment="buy/sell")
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0, comment="盈亏")
    trade_time = Column(Date, nullable=False)
    signal_reason = Column(String(200), default="")
