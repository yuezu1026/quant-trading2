"""
仪表盘 API
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.ws import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# 全局引擎引用（由 app.py 注入）
_paper_engine = None


def set_paper_engine(engine) -> None:
    global _paper_engine
    _paper_engine = engine


@router.get("/overview")
async def get_overview() -> dict:
    """获取账户概览"""
    if _paper_engine:
        return _paper_engine.get_dashboard_data()
    return {
        "cash": 0,
        "total_asset": 0,
        "realized_pnl": 0,
        "positions": {},
        "is_running": False,
    }


@router.get("/positions")
async def get_positions() -> dict:
    """获取持仓列表"""
    if _paper_engine:
        return {"positions": _paper_engine.positions}
    return {"positions": {}}


@router.get("/equity_curve")
async def get_equity_curve(
    strategy_name: Optional[str] = None,
    days: int = 90,
) -> dict:
    """
    获取资产曲线数据。

    返回最近N天的每日资产快照，供前端绘图。
    """
    from data import Repository

    repo = Repository()
    # 简化实现：从数据库读取交易记录聚合
    trades = repo.get_trades(strategy_name=strategy_name)

    if trades.empty:
        return {"dates": [], "values": []}

    # 按日期聚合（简化）
    return {
        "message": "资产曲线需要回测记录器输出，当前为简化版本",
        "trade_count": len(trades),
    }


@router.websocket("/ws")
async def dashboard_ws(ws: WebSocket):
    """仪表盘 WebSocket"""
    await ws_manager.connect(ws)
    try:
        while True:
            # 保持连接，接收客户端消息（如订阅请求）
            data = await ws.receive_text()
            import json
            msg = json.loads(data)

            if msg.get("action") == "subscribe":
                channel = msg.get("channel", "dashboard")
                await ws_manager.subscribe(ws, channel)

            elif msg.get("action") == "ping":
                await ws_manager.send_to(ws, "pong", {"time": datetime.now().isoformat()})

    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)
