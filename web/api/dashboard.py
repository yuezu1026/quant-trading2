"""
仪表盘 API — 含自驱动模拟数据，开箱即用
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.ws import manager as ws_manager, push_account_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ============================================================================
# 模拟交易数据生成器
# ============================================================================

class DashboardSimulator:
    """
    仪表盘模拟数据源 — 用随机波动生成真实感的账户数据。

    启动后在后台线程中运行，每3秒更新一次资产数据，
    并通过 WebSocket 推送给所有已连接的客户端。
    """

    def __init__(self):
        self._cash: float = 0.0
        self._total_asset: float = 100_000.0
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self._positions: dict = {}
        self._is_running: bool = False
        self._day: int = 0
        self._thread: Optional[threading.Thread] = None

        # 初始化模拟持仓
        self._init_positions()

    def _init_positions(self):
        codes = ["600036.SH", "000001.SZ", "600519.SH"]
        names = ["招商银行", "平安银行", "贵州茅台"]
        prices = [38.50, 12.30, 1750.0]
        qtys = [2000, 5000, 100]
        costs = [37.80, 11.95, 1680.0]

        for i, code in enumerate(codes):
            self._positions[code] = {
                "code": code,
                "name": names[i],
                "quantity": qtys[i],
                "available": qtys[i],
                "avg_cost": costs[i],
                "current_price": prices[i],
                "market_value": qtys[i] * prices[i],
                "unrealized_pnl": (prices[i] - costs[i]) * qtys[i],
            }

        self._cash = self._total_asset - sum(
            p["market_value"] for p in self._positions.values()
        )
        # 确保现金不为负
        self._cash = max(0, self._cash)
        self._total_asset = self._cash + sum(
            p["market_value"] for p in self._positions.values()
        )

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("仪表盘模拟器启动")

    def stop(self):
        self._is_running = False

    def _run(self):
        rng = random.Random(42)
        while self._is_running:
            time.sleep(3)
            self._day += 1

            # 随机更新每只股票价格 (±2%)
            for code, pos in list(self._positions.items()):
                change = rng.gauss(0.0005, 0.015)
                new_price = pos["current_price"] * (1 + change)
                new_price = max(new_price, pos["avg_cost"] * 0.7)
                pos["current_price"] = round(new_price, 2)
                pos["market_value"] = round(pos["quantity"] * new_price, 2)
                pos["unrealized_pnl"] = round(
                    (new_price - pos["avg_cost"]) * pos["quantity"], 2
                )

                # 模拟交易: 每 ~10 秒随机卖出部分股票产生已实现盈亏
                if self._day % 4 == 0 and pos["quantity"] >= 100:
                    sell_qty = ((rng.randint(1, 3) * 100) // 100) * 100
                    sell_qty = min(sell_qty, pos["quantity"])
                    if sell_qty > 0:
                        trade_pnl = round((new_price - pos["avg_cost"]) * sell_qty, 2)
                        self._realized_pnl = round(self._realized_pnl + trade_pnl, 2)
                        self._cash = round(self._cash + new_price * sell_qty, 2)
                        pos["quantity"] -= sell_qty
                        pos["available"] -= sell_qty
                        pos["market_value"] = round(pos["quantity"] * new_price, 2)
                        pos["unrealized_pnl"] = round(
                            (new_price - pos["avg_cost"]) * pos["quantity"], 2
                        )

                        # 如果清仓，移除持仓
                        if pos["quantity"] <= 0:
                            del self._positions[code]

            # 偶尔建新仓（现金足够时）
            if self._day % 12 == 0 and self._cash > 5000:
                new_codes = ["600000.SH", "000858.SZ", "601318.SH"]
                new_names = ["浦发银行", "五粮液", "中国平安"]
                idx = rng.randint(0, 2)
                if new_codes[idx] not in self._positions:
                    price = rng.uniform(10, 200)
                    qty = rng.randint(5, 20) * 100
                    cost = price * qty
                    if cost <= self._cash * 0.3:
                        self._cash = round(self._cash - cost, 2)
                        self._positions[new_codes[idx]] = {
                            "code": new_codes[idx],
                            "name": new_names[idx],
                            "quantity": qty,
                            "available": qty,
                            "avg_cost": round(price, 2),
                            "current_price": round(price, 2),
                            "market_value": round(cost, 2),
                            "unrealized_pnl": 0.0,
                        }

            # 更新总资产
            total_mv = sum(p["market_value"] for p in self._positions.values())
            self._unrealized_pnl = sum(p["unrealized_pnl"] for p in self._positions.values())
            self._total_asset = round(self._cash + total_mv, 2)

            # 异步推送
            try:
                data = self.get_dashboard_data()
                loop = asyncio.new_event_loop()
                loop.run_until_complete(push_account_update(data))
                loop.close()
            except Exception:
                pass

    def get_dashboard_data(self) -> dict:
        return {
            "cash": self._cash,
            "frozen_cash": 0.0,
            "total_asset": self._total_asset,
            "realized_pnl": self._realized_pnl,
            "unrealized_pnl": self._unrealized_pnl,
            "positions": self._positions,
            "is_running": self._is_running,
            "subscribed_codes": list(self._positions.keys()),
        }

    @property
    def positions(self) -> dict:
        return self._positions

    @property
    def account(self):
        from core.types import Account, Position

        acc = Account(
            cash=self._cash,
            total_asset=self._total_asset,
            realized_pnl=self._realized_pnl,
        )
        for code, p in self._positions.items():
            acc.positions[code] = Position(
                code=code,
                quantity=p["quantity"],
                available=p["available"],
                avg_cost=p["avg_cost"],
                current_price=p["current_price"],
                market_value=p["market_value"],
                unrealized_pnl=p["unrealized_pnl"],
            )
        return acc


# 全局模拟器
_simulator: Optional[DashboardSimulator] = None


def get_simulator() -> DashboardSimulator:
    global _simulator
    if _simulator is None:
        _simulator = DashboardSimulator()
    return _simulator


def start_simulator():
    sim = get_simulator()
    sim.start()


# ============================================================================
# 兼容旧接口
# ============================================================================

_paper_engine = None


def set_paper_engine(engine) -> None:
    global _paper_engine
    _paper_engine = engine


# ============================================================================
# API
# ============================================================================

@router.get("/config")
async def get_config() -> dict:
    """获取系统配置：数据源、策略信息"""
    import os
    import yaml

    # 读取数据源配置
    data_source = "unknown"
    tushare_ok = False
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "settings.yaml"
    )
    config_path = os.path.normpath(config_path)
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        data_source = cfg.get("data", {}).get("provider", "unknown")
        # 检查 token 是否配置
        token = cfg.get("data", {}).get("tushare_token", "")
        if not token:
            token = os.environ.get("TUSHARE_TOKEN", "")
        # 尝试 local 配置
        local_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "settings.local.yaml"
        )
        local_path = os.path.normpath(local_path)
        if os.path.exists(local_path):
            with open(local_path, encoding="utf-8") as f:
                local_cfg = yaml.safe_load(f)
            local_token = local_cfg.get("data", {}).get("tushare_token", "")
            if local_token:
                token = local_token
        tushare_ok = bool(token)
    except Exception:
        pass

    # 策略信息
    strategies = []
    try:
        from .strategy import _strategies
        for name, s in _strategies.items():
            strategies.append({
                "name": name,
                "class_name": s.get("class_name", ""),
                "is_running": s.get("running", False),
                "params": s.get("params", {}),
            })
    except Exception:
        pass

    # 如果没有注册策略，展示默认策略
    if not strategies:
        strategies = [{
            "name": "MA_Cross_5_20",
            "class_name": "MACrossStrategy",
            "is_running": False,
            "params": {"fast_period": 5, "slow_period": 20, "fixed_quantity": 0},
        }]

    # 是否使用 Docker
    in_docker = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", "")

    return {
        "data_source": data_source,
        "tushare_configured": tushare_ok,
        "environment": "docker" if in_docker else "local",
        "strategies": strategies,
    }


@router.get("/overview")
async def get_overview() -> dict:
    """获取账户概览"""
    # 优先实盘引擎
    if _paper_engine:
        return _paper_engine.get_dashboard_data()
    # 回退到仪表盘模拟器
    return get_simulator().get_dashboard_data()


@router.get("/positions")
async def get_positions() -> dict:
    if _paper_engine:
        return {"positions": _paper_engine.positions}
    return {"positions": get_simulator().positions}


@router.get("/equity_curve")
async def get_equity_curve(days: int = 90) -> dict:
    """
    资产曲线 — 生成模拟的回测曲线供仪表盘绘图。
    """
    rng = random.Random(42)

    dates = []
    values = []
    price = 100_000.0
    for i in range(days, 0, -1):
        d = date.today()
        # 简单往前推日期
        d = d.replace(day=max(1, d.day - i)) if d.day > i else d
        dates.append(d.isoformat() if hasattr(d, 'isoformat') else str(d))
        change = rng.gauss(0.0003, 0.01)
        price *= (1 + change)
        values.append(round(price, 2))

    return {"dates": dates, "values": values}


@router.websocket("/ws")
async def dashboard_ws(ws: WebSocket):
    """仪表盘 WebSocket"""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            import json
            msg = json.loads(data)

            if msg.get("action") == "subscribe":
                channel = msg.get("channel", "dashboard")
                await ws_manager.subscribe(ws, channel)

            elif msg.get("action") == "ping":
                await ws_manager.send_to(ws, "pong", {"time": datetime.now().isoformat()})

            elif msg.get("action") == "get_overview":
                overview = get_simulator().get_dashboard_data()
                await ws_manager.send_to(ws, "account", overview)

    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)
