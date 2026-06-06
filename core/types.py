"""
核心数据类型定义

所有模块共享的数据结构，使用 pydantic 进行校验。
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# 枚举类型
# ============================================================================

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"      # 市价单
    LIMIT = "limit"        # 限价单


class OrderStatus(str, Enum):
    PENDING = "pending"        # 待提交
    SUBMITTED = "submitted"    # 已提交
    PARTIAL = "partial"        # 部分成交
    FILLED = "filled"          # 全部成交
    CANCELLED = "cancelled"    # 已撤销
    REJECTED = "rejected"      # 被拒绝


class EventType(str, Enum):
    MARKET_DATA = "market_data"           # 行情数据
    BAR = "bar"                           # K线完成
    SIGNAL = "signal"                     # 策略信号
    ORDER = "order"                       # 订单
    CANCEL_ORDER = "cancel_order"         # 撤单
    FILL = "fill"                         # 成交
    POSITION_UPDATE = "position_update"   # 持仓更新
    ACCOUNT_UPDATE = "account_update"     # 账户更新
    RISK_ALERT = "risk_alert"             # 风控告警
    ENGINE_START = "engine_start"         # 引擎启动
    ENGINE_STOP = "engine_stop"           # 引擎停止


# ============================================================================
# 市场数据
# ============================================================================

class Bar(BaseModel):
    """单根K线数据"""
    code: str = Field(..., description="股票代码，如 600000.SH")
    date: date = Field(..., description="交易日期")
    time: Optional[str] = Field(default=None, description="日内时间 HH:MM:SS")
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(..., description="成交量（股）")
    amount: float = Field(..., description="成交额（元）")
    pre_close: Optional[float] = Field(default=None, description="前收盘价")
    is_st: bool = Field(default=False, description="是否ST")
    up_limit: Optional[float] = Field(default=None, description="涨停价")
    down_limit: Optional[float] = Field(default=None, description="跌停价")

    @property
    def change_pct(self) -> float:
        """涨跌幅(%)"""
        if self.pre_close and self.pre_close > 0:
            return (self.close - self.pre_close) / self.pre_close * 100
        return 0.0

    @property
    def is_limit_up(self) -> bool:
        """是否涨停"""
        if self.up_limit:
            return self.close >= self.up_limit
        return False

    @property
    def is_limit_down(self) -> bool:
        """是否跌停"""
        if self.down_limit:
            return self.close <= self.down_limit
        return False


class Tick(BaseModel):
    """逐笔/快照数据"""
    code: str
    datetime: datetime
    price: float
    volume: float
    bid1: float = 0.0
    ask1: float = 0.0
    bid_vol1: float = 0.0
    ask_vol1: float = 0.0


# ============================================================================
# 交易相关
# ============================================================================

class Signal(BaseModel):
    """策略产生的交易信号"""
    code: str
    side: OrderSide
    quantity: int = Field(..., ge=100, description="目标数量（股），须为100的整数倍")
    price: Optional[float] = Field(default=None, description="限价，None为市价")
    order_type: OrderType = OrderType.LIMIT
    reason: str = Field(default="", description="信号理由（便于回顾）")
    confidence: float = Field(default=1.0, ge=0, le=1, description="信号置信度 0~1")

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_lot(cls, v: int) -> int:
        if v % 100 != 0:
            raise ValueError(f"数量必须是100的整数倍，收到 {v}")
        return v


class Order(BaseModel):
    """订单"""
    order_id: str
    code: str
    side: OrderSide
    quantity: int
    filled_quantity: int = 0
    price: float = 0.0            # 委托价格
    avg_fill_price: float = 0.0   # 成交均价
    order_type: OrderType = OrderType.LIMIT
    status: OrderStatus = OrderStatus.PENDING
    create_time: datetime = Field(default_factory=datetime.now)
    update_time: Optional[datetime] = None
    signal: Optional[Signal] = None  # 关联的信号

    @property
    def is_finished(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )


class Fill(BaseModel):
    """成交记录"""
    fill_id: str
    order_id: str
    code: str
    side: OrderSide
    quantity: int
    price: float
    commission: float = 0.0    # 佣金
    tax: float = 0.0           # 印花税
    fill_time: datetime = Field(default_factory=datetime.now)


class Position(BaseModel):
    """持仓"""
    code: str
    quantity: int = 0                     # 当前持仓（股）
    available: int = 0                    # 可卖数量（A股 T+1: 今买不可卖）
    avg_cost: float = 0.0                 # 持仓均价
    current_price: float = 0.0            # 当前市价
    market_value: float = 0.0             # 市值
    unrealized_pnl: float = 0.0           # 浮动盈亏
    realized_pnl: float = 0.0             # 已实现盈亏


class Account(BaseModel):
    """账户"""
    cash: float = 0.0                     # 可用资金
    frozen_cash: float = 0.0              # 冻结资金（已下单未成交）
    total_asset: float = 0.0              # 总资产（现金 + 持仓市值）
    positions: dict[str, Position] = Field(default_factory=dict)
    realized_pnl: float = 0.0             # 累计已实现盈亏


# ============================================================================
# 风险控制
# ============================================================================

class RiskAlert(BaseModel):
    """风控告警"""
    code: str
    rule: str
    message: str
    severity: str = "warning"  # warning / critical
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# 事件
# ============================================================================

class Event(BaseModel):
    """事件总线中的事件"""
    type: EventType
    data: Bar | Tick | Signal | Order | Fill | Account | RiskAlert | dict
    timestamp: datetime = Field(default_factory=datetime.now)
