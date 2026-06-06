"""
券商网关抽象基类

所有实盘网关（QMT、XTP、华泰MATIC等）需实现此接口。
网关负责：
- 连接/断连管理
- 下单/撤单
- 查询持仓/资金
- 订阅行情
- 订单状态回调
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Callable

from core.types import (
    Order, OrderSide, OrderType, OrderStatus,
    Fill, Position, Account, Bar, Tick,
)


class GatewayCallback:
    """网关回调接口 — 网关通过回调通知上层"""

    def on_order_update(self, order: Order) -> None:
        """订单状态变更"""
        pass

    def on_fill(self, fill: Fill) -> None:
        """成交回报"""
        pass

    def on_position_update(self, positions: list[Position]) -> None:
        """持仓更新"""
        pass

    def on_account_update(self, account: Account) -> None:
        """账户资金更新"""
        pass

    def on_bar(self, bar: Bar) -> None:
        """行情数据(K线)"""
        pass

    def on_tick(self, tick: Tick) -> None:
        """行情数据(逐笔)"""
        pass

    def on_error(self, error: str) -> None:
        """错误通知"""
        pass

    def on_disconnected(self) -> None:
        """连接断开"""
        pass

    def on_reconnected(self) -> None:
        """重连成功"""
        pass


class TradingGateway(ABC):
    """
    券商网关抽象基类。

    所有实盘券商API的封装都必须实现此接口。
    """

    name: str = "base_gateway"

    def __init__(self):
        self._callback: Optional[GatewayCallback] = None
        self._connected = False
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, **kwargs) -> bool:
        """
        连接券商服务器。

        Returns:
            bool: 连接是否成功
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    def reconnect(self) -> bool:
        """重新连接"""
        ...

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> str:
        return self._last_error

    # ------------------------------------------------------------------
    # 交易接口
    # ------------------------------------------------------------------

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """
        提交订单到券商。

        Args:
            order: 待提交订单（order_id 已生成）

        Returns:
            订单（含券商返回的订单状态和系统订单号）
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤销订单。

        Args:
            order_id: 本地订单ID

        Returns:
            bool: 撤单请求是否成功发送
        """
        ...

    @abstractmethod
    def query_order(self, order_id: str) -> Optional[Order]:
        """查询订单状态"""
        ...

    @abstractmethod
    def query_orders(self, code: Optional[str] = None) -> list[Order]:
        """查询所有未完成订单"""
        ...

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @abstractmethod
    def query_positions(self) -> list[Position]:
        """查询持仓"""
        ...

    @abstractmethod
    def query_account(self) -> Account:
        """查询账户资金"""
        ...

    # ------------------------------------------------------------------
    # 行情订阅
    # ------------------------------------------------------------------

    @abstractmethod
    def subscribe(self, codes: list[str]) -> None:
        """订阅实时行情"""
        ...

    @abstractmethod
    def unsubscribe(self, codes: list[str]) -> None:
        """取消订阅"""
        ...

    # ------------------------------------------------------------------
    # 回调设置
    # ------------------------------------------------------------------

    def set_callback(self, callback: GatewayCallback) -> None:
        """设置回调对象"""
        self._callback = callback

    def _notify(self, method: str, *args, **kwargs) -> None:
        """安全调用回调（防异常传播）"""
        import logging
        logger = logging.getLogger(__name__)

        if self._callback is None:
            return

        try:
            fn = getattr(self._callback, method, None)
            if fn:
                fn(*args, **kwargs)
        except Exception:
            logger.exception(f"回调异常: {method}")

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    @staticmethod
    @abstractmethod
    def get_config_schema() -> dict:
        """返回此网关需要的配置项说明"""
        ...
