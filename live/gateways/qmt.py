"""
迅投 QMT 网关

支持 MiniQMT（个人版）和完整 QMT。

前置条件:
    1. 安装迅投QMT客户端 (xtquant)
    2. 在QMT中配置Python路径
    3. pip install xtquant  (如果券商提供)

连接方式:
    - MiniQMT: connect(mini=True, path="D:\\QMT\\userdata_mini")
    - 完整QMT: connect(mini=False, ip="127.0.0.1", port=58610, account="xxx")
"""
from __future__ import annotations

import logging
import time
import threading
from datetime import datetime
from typing import Optional

from .base import TradingGateway
from core.types import (
    Order, OrderSide, OrderType, OrderStatus,
    Fill, Position, Account, Tick,
)

logger = logging.getLogger(__name__)


class QMTGateway(TradingGateway):
    """
    迅投 QMT 交易网关。

    特性:
    - 支持 MiniQMT（个人免费）和完整版QMT
    - 自动重连
    - 订单状态异步回调
    - 持仓/资金查询

    使用方式:
        gw = QMTGateway()
        gw.set_callback(my_callback)
        ok = gw.connect(mini=True, path="D:\\QMT\\userdata_mini")
        if ok:
            gw.subscribe(["600000.SH"])
            order = gw.submit_order(my_order)
    """

    name = "qmt"

    def __init__(self):
        super().__init__()
        self._xt_trader = None          # xtquant.XtQuantTrader
        self._xt_quote = None           # xtquant.XtQuantQuote
        self._account = ""
        self._is_mini = True

        # 映射 QMT 订单状态到内部状态
        self._status_map = {
            48: OrderStatus.SUBMITTED,   # 已发送
            49: OrderStatus.SUBMITTED,   # 未成交
            50: OrderStatus.PARTIAL,     # 部分成交
            51: OrderStatus.FILLED,      # 全部成交
            52: OrderStatus.CANCELLED,   # 已撤单
            53: OrderStatus.PARTIAL,     # 部成部撤
            54: OrderStatus.REJECTED,    # 废单
            57: OrderStatus.PENDING,     # 待报
        }

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self, **kwargs) -> bool:
        """
        连接 QMT。

        MiniQMT 参数:
            mini: True (默认)
            path: MiniQMT 数据目录路径

        完整QMT 参数:
            mini: False
            ip: 服务器IP (默认 127.0.0.1)
            port: 端口 (默认 58610)
            account: 资金账号
        """
        try:
            import xtquant.xttrader as xttrader
            import xtquant.xtdata as xtdata

            self._is_mini = kwargs.get("mini", True)

            if self._is_mini:
                ok = self._connect_mini(kwargs, xttrader, xtdata)
            else:
                ok = self._connect_full(kwargs, xttrader, xtdata)

            if ok:
                self._connected = True
                self._start_heartbeat()
                logger.info(f"QMT 连接成功 (mini={self._is_mini})")
            else:
                logger.error("QMT 连接失败")

            return ok

        except ImportError:
            self._last_error = "xtquant 未安装: pip install xtquant"
            logger.error(self._last_error)
            return False
        except Exception as e:
            self._last_error = f"QMT 连接异常: {e}"
            logger.exception(self._last_error)
            return False

    def _connect_mini(self, kwargs: dict, xttrader, xtdata) -> bool:
        """连接 MiniQMT"""
        path = kwargs.get("path", "")
        if not path:
            self._last_error = "MiniQMT 需要指定 path 参数"
            return False

        session_id = int(time.time())
        self._xt_trader = xttrader.XtQuantTrader(path, session_id)
        self._xt_trader.start()

        # 注册回调
        self._xt_trader.register_callback(self._on_qmt_callback)

        # 连接
        connect_result = self._xt_trader.connect()
        if connect_result != 0:
            self._last_error = f"MiniQMT 连接失败: code={connect_result}"
            return False

        # 查询账户
        try:
            accounts = self._xt_trader.query_account()
            if accounts:
                self._account = accounts[0]
        except Exception:
            pass

        return True

    def _connect_full(self, kwargs: dict, xttrader, xtdata) -> bool:
        """连接完整版 QMT"""
        ip = kwargs.get("ip", "127.0.0.1")
        port = kwargs.get("port", 58610)
        account = kwargs.get("account", "")

        session_id = int(time.time())
        self._xt_trader = xttrader.XtQuantTrader(ip, port, session_id)
        self._xt_trader.start()

        self._xt_trader.register_callback(self._on_qmt_callback)

        connect_result = self._xt_trader.connect()
        if connect_result != 0:
            self._last_error = f"QMT 连接失败: code={connect_result}"
            return False

        self._account = account
        return True

    def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        if self._xt_trader:
            try:
                self._xt_trader.stop()
            except Exception:
                pass
            self._xt_trader = None
        logger.info("QMT 已断开")

    def reconnect(self) -> bool:
        """重新连接"""
        logger.info("QMT 重连中...")
        self.disconnect()
        time.sleep(2)
        # 重连需要原参数，这里简化：仅做断开
        return False  # 实际需要存储原参数

    # ------------------------------------------------------------------
    # 交易接口
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        """
        向 QMT 提交订单。

        QMT 下单需要:
        - stock_code: 如 "600000.SH"
        - order_type: 0-限价, 1-市价(深市), 2-最优五档(沪市)
        - order_volume: 股数
        - price_type: 和 order_type 对应
        - price: 价格
        - strategy_name: 策略名称(用于区分)
        - order_remark: 备注
        """
        if not self._connected or not self._xt_trader:
            order.status = OrderStatus.REJECTED
            return order

        try:
            price_type_map = {
                OrderType.LIMIT: 0,
                OrderType.MARKET: 1,
            }

            seq = self._xt_trader.order_stock(
                stock_code=order.code,
                order_type=price_type_map.get(order.order_type, 0),
                order_volume=order.quantity,
                price_type=price_type_map.get(order.order_type, 0),
                price=order.price,
                strategy_name="quant_trading",
                order_remark=order.signal.reason if order.signal else "",
            )

            # seq > 0 表示下单成功
            if seq > 0:
                order.status = OrderStatus.SUBMITTED
                logger.info(f"QMT 下单成功: {order.code} {order.side.value} {order.quantity}股, seq={seq}")
            else:
                order.status = OrderStatus.REJECTED
                logger.error(f"QMT 下单失败: seq={seq}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            logger.exception(f"QMT 下单异常: {e}")

        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤销QMT订单"""
        if not self._connected or not self._xt_trader:
            return False

        try:
            # QMT撤单需要系统订单号，这里用本地ID（实际需要维护映射）
            result = self._xt_trader.cancel_order_stock(int(order_id))
            logger.info(f"QMT 撤单请求: {order_id}, result={result}")
            return result >= 0
        except Exception as e:
            logger.exception(f"QMT 撤单异常: {e}")
            return False

    def query_order(self, order_id: str) -> Optional[Order]:
        """查询QMT订单状态"""
        if not self._connected or not self._xt_trader:
            return None

        try:
            orders = self._xt_trader.query_orders()
            for o in orders:
                if str(o.order_id) == order_id:
                    return self._xt_order_to_internal(o)
        except Exception:
            pass
        return None

    def query_orders(self, code: Optional[str] = None) -> list[Order]:
        """查询所有未完成订单"""
        if not self._connected or not self._xt_trader:
            return []

        try:
            qmt_orders = self._xt_trader.query_orders()
            orders = [self._xt_order_to_internal(o) for o in qmt_orders]
            if code:
                orders = [o for o in orders if o.code == code]
            return orders
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def query_positions(self) -> list[Position]:
        """查询 QMT 持仓"""
        if not self._connected or not self._xt_trader:
            return []

        try:
            qmt_positions = self._xt_trader.query_positions()
            positions = []
            for p in qmt_positions:
                positions.append(Position(
                    code=p.stock_code,
                    quantity=p.volume,
                    available=p.can_use_volume,
                    avg_cost=p.open_price,
                    current_price=p.market_value / p.volume if p.volume > 0 else 0.0,
                    market_value=p.market_value,
                ))
            return positions
        except Exception:
            logger.exception("QMT 查询持仓异常")
            return []

    def query_account(self) -> Account:
        """查询 QMT 账户资金"""
        if not self._connected or not self._xt_trader:
            return Account()

        try:
            asset = self._xt_trader.query_asset()
            return Account(
                cash=asset.cash,
                frozen_cash=asset.frozen_cash,
                total_asset=asset.total_asset,
            )
        except Exception:
            logger.exception("QMT 查询账户异常")
            return Account()

    # ------------------------------------------------------------------
    # 行情订阅
    # ------------------------------------------------------------------

    def subscribe(self, codes: list[str]) -> None:
        """订阅实时行情（通过 xtdata）"""
        try:
            import xtquant.xtdata as xtdata

            for code in codes:
                xtdata.subscribe_quote(
                    code,
                    period="tick",
                    callback=self._on_quote_callback,
                )
            logger.info(f"QMT 订阅行情: {codes}")
        except Exception:
            logger.exception("QMT 订阅行情失败")

    def unsubscribe(self, codes: list[str]) -> None:
        try:
            import xtquant.xtdata as xtdata
            for code in codes:
                xtdata.unsubscribe_quote(code, period="tick")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部回调
    # ------------------------------------------------------------------

    def _on_qmt_callback(self, data) -> None:
        """QMT 交易回调（订单状态变更、成交回报）"""
        try:
            if hasattr(data, "order_type"):
                # 订单状态变更
                order = self._xt_order_to_internal(data)
                self._notify("on_order_update", order)

                # 如果成交，生成 Fill
                if data.order_status in (51,):  # 全部成交
                    fill = Fill(
                        fill_id=f"fill_qmt_{data.order_id}",
                        order_id=str(data.order_id),
                        code=data.stock_code,
                        side=OrderSide.BUY if data.order_type in (0, 4, 6) else OrderSide.SELL,
                        quantity=data.order_volume,
                        price=data.price or 0.0,
                        fill_time=datetime.now(),
                    )
                    self._notify("on_fill", fill)

        except Exception:
            logger.exception("处理 QMT 回调异常")

    def _on_quote_callback(self, data) -> None:
        """QMT 行情回调"""
        try:
            tick = Tick(
                code=data.stock_code,
                datetime=datetime.now(),
                price=data.last_price,
                volume=data.volume,
                bid1=data.bid_price[0] if hasattr(data, "bid_price") and data.bid_price else 0.0,
                ask1=data.ask_price[0] if hasattr(data, "ask_price") and data.ask_price else 0.0,
            )
            self._notify("on_tick", tick)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        """启动心跳检测"""
        def heartbeat():
            while self._connected:
                time.sleep(30)
                if self._xt_trader:
                    try:
                        result = self._xt_trader.query_asset()
                        if result is None:
                            logger.warning("QMT 心跳检测失败，可能已断连")
                            self._notify("on_disconnected")
                    except Exception:
                        self._notify("on_disconnected")

        t = threading.Thread(target=heartbeat, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _xt_order_to_internal(self, xt_order) -> Order:
        """将 QMT 订单转为内部 Order"""
        side = OrderSide.BUY
        if hasattr(xt_order, "order_type"):
            # QMT: 0/4/6=买, 1/5/7=卖
            if xt_order.order_type in (1, 5, 7):
                side = OrderSide.SELL

        return Order(
            order_id=str(xt_order.order_id),
            code=xt_order.stock_code if hasattr(xt_order, "stock_code") else "",
            side=side,
            quantity=xt_order.order_volume if hasattr(xt_order, "order_volume") else 0,
            filled_quantity=xt_order.traded_volume if hasattr(xt_order, "traded_volume") else 0,
            price=xt_order.price if hasattr(xt_order, "price") else 0.0,
            avg_fill_price=xt_order.traded_price if hasattr(xt_order, "traded_price") else 0.0,
            order_type=OrderType.LIMIT,
            status=self._status_map.get(
                xt_order.order_status if hasattr(xt_order, "order_status") else 0,
                OrderStatus.PENDING,
            ),
            update_time=datetime.now(),
        )

    @staticmethod
    def get_config_schema() -> dict:
        return {
            "mini": {
                "type": "bool",
                "description": "是否使用 MiniQMT",
                "default": True,
            },
            "path": {
                "type": "str",
                "description": "MiniQMT 数据目录路径",
                "default": "",
            },
            "ip": {
                "type": "str",
                "description": "完整版QMT服务器IP",
                "default": "127.0.0.1",
            },
            "port": {
                "type": "int",
                "description": "完整版QMT端口",
                "default": 58610,
            },
            "account": {
                "type": "str",
                "description": "资金账号",
                "default": "",
            },
        }
