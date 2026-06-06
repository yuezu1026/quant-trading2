"""
订单管理器

负责:
- 订单生命周期跟踪（创建→提交→成交/撤销）
- 订单状态同步（本地 ↔ 券商）
- 超时重试与异常恢复
- 订单去重
"""
from __future__ import annotations

import logging
import uuid
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

from core.types import (
    Order, OrderSide, OrderType, OrderStatus,
    Fill, Signal,
)

logger = logging.getLogger(__name__)


class OrderManager:
    """
    订单管理器。

    特性:
    - 订单ID生成
    - 状态机管理
    - 订单超时检测
    - 订单簿维护

    状态流转:
        PENDING → SUBMITTED → PARTIAL → FILLED
            ↓         ↓         ↓
        CANCELLED  CANCELLED  CANCELLED
            ↓
        REJECTED
    """

    # 有效状态流转
    _VALID_TRANSITIONS = {
        OrderStatus.PENDING: {
            OrderStatus.SUBMITTED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.SUBMITTED: {
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        },
        OrderStatus.PARTIAL: {
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        },
    }

    def __init__(self, order_timeout_seconds: int = 300):
        self._orders: dict[str, Order] = {}           # order_id → Order
        self._fills: list[Fill] = []
        self._id_map: dict[str, str] = {}             # broker_order_id → local_order_id
        self._timeout = order_timeout_seconds

        self._on_status_change: Optional[Callable[[Order, OrderStatus], None]] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 订单 CRUD
    # ------------------------------------------------------------------

    def create_order(self, signal: Signal) -> Order:
        """从信号创建订单"""
        order_id = f"ord_{uuid.uuid4().hex[:8]}"

        order = Order(
            order_id=order_id,
            code=signal.code,
            side=signal.side,
            quantity=signal.quantity,
            price=signal.price or 0.0,
            order_type=signal.order_type,
            status=OrderStatus.PENDING,
            signal=signal,
        )

        with self._lock:
            self._orders[order_id] = order

        logger.info(f"创建订单: {order_id} {signal.side.value} {signal.code} {signal.quantity}股")
        return order

    def create_manual_order(
        self, code: str, side: str, quantity: int, price: float = 0.0
    ) -> Order:
        """手动创建订单"""
        order_id = f"ord_{uuid.uuid4().hex[:8]}"

        order = Order(
            order_id=order_id,
            code=code,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            quantity=quantity,
            price=price,
            order_type=OrderType.LIMIT if price > 0 else OrderType.MARKET,
            status=OrderStatus.PENDING,
        )

        with self._lock:
            self._orders[order_id] = order

        return order

    def update_status(self, order_id: str, new_status: OrderStatus, **kwargs) -> bool:
        """
        更新订单状态。

        Returns:
            是否成功更新
        """
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                logger.warning(f"订单不存在: {order_id}")
                return False

            old_status = order.status

            # 检查状态流转是否合法
            if new_status != old_status:
                valid = self._VALID_TRANSITIONS.get(old_status, set())
                if new_status not in valid:
                    logger.warning(
                        f"非法状态流转: {order_id} {old_status.value} → {new_status.value}"
                    )
                    return False

                if self._on_status_change:
                    self._on_status_change(order, new_status)

            order.status = new_status
            order.update_time = datetime.now()

            for k, v in kwargs.items():
                if hasattr(order, k):
                    setattr(order, k, v)

        logger.debug(f"订单状态: {order_id} {old_status.value} → {new_status.value}")
        return True

    def record_fill(self, order_id: str, fill: Fill) -> None:
        """记录成交"""
        with self._lock:
            self._fills.append(fill)

            order = self._orders.get(order_id)
            if order:
                order.filled_quantity += fill.quantity
                if order.filled_quantity >= order.quantity:
                    order.status = OrderStatus.FILLED
                else:
                    order.status = OrderStatus.PARTIAL
                order.avg_fill_price = (
                    (order.avg_fill_price * (order.filled_quantity - fill.quantity)
                     + fill.price * fill.quantity)
                    / order.filled_quantity
                )
                order.update_time = datetime.now()

    def map_broker_id(self, local_id: str, broker_id: str) -> None:
        """映射本地订单ID → 券商系统订单ID"""
        self._id_map[broker_id] = local_id

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_order_by_broker_id(self, broker_id: str) -> Optional[Order]:
        local_id = self._id_map.get(broker_id)
        if local_id:
            return self._orders.get(local_id)
        return None

    def get_orders(self, status: Optional[OrderStatus] = None) -> list[Order]:
        """获取订单列表"""
        with self._lock:
            orders = list(self._orders.values())
            if status:
                orders = [o for o in orders if o.status == status]
            return orders

    def get_pending_orders(self) -> list[Order]:
        """获取所有未完成订单（待成交/部分成交）"""
        return self.get_orders(OrderStatus.SUBMITTED) + self.get_orders(OrderStatus.PARTIAL)

    def get_fills(self, order_id: Optional[str] = None) -> list[Fill]:
        """获取成交记录"""
        if order_id:
            return [f for f in self._fills if f.order_id == order_id]
        return list(self._fills)

    # ------------------------------------------------------------------
    # 订单超时检测
    # ------------------------------------------------------------------

    def check_timeouts(self) -> list[Order]:
        """检查超时订单（超时自动撤销）"""
        timeout_orders = []
        now = datetime.now()
        threshold = now - timedelta(seconds=self._timeout)

        with self._lock:
            for order in self._orders.values():
                if order.status in (OrderStatus.SUBMITTED, OrderStatus.PENDING):
                    if order.create_time < threshold:
                        timeout_orders.append(order)

        return timeout_orders

    def cancel_timeout_orders(self) -> int:
        """撤销所有超时订单"""
        timeout_orders = self.check_timeouts()
        count = 0
        for order in timeout_orders:
            if self.update_status(order.order_id, OrderStatus.CANCELLED):
                count += 1
                logger.warning(f"订单超时撤销: {order.order_id} {order.code}")
        return count

    # ------------------------------------------------------------------
    # 回调
    # ------------------------------------------------------------------

    def set_status_callback(self, cb: Callable[[Order, OrderStatus], None]) -> None:
        """设置状态变更回调"""
        self._on_status_change = cb

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "total": len(self._orders),
                "pending": len(self.get_orders(OrderStatus.PENDING)),
                "submitted": len(self.get_orders(OrderStatus.SUBMITTED)),
                "partial": len(self.get_orders(OrderStatus.PARTIAL)),
                "filled": len(self.get_orders(OrderStatus.FILLED)),
                "cancelled": len(self.get_orders(OrderStatus.CANCELLED)),
                "rejected": len(self.get_orders(OrderStatus.REJECTED)),
                "fills": len(self._fills),
            }
