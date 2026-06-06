"""
WebSocket 实时推送

向前端推送实时行情、账户变化、成交通知。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._subscribed_channels: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        self._subscribed_channels[ws] = {"dashboard"}
        logger.info(f"WebSocket 连接: {len(self._connections)} 活跃")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        self._subscribed_channels.pop(ws, None)
        logger.info(f"WebSocket 断开: {len(self._connections)} 活跃")

    async def subscribe(self, ws: WebSocket, channel: str) -> None:
        """订阅频道"""
        if ws in self._subscribed_channels:
            self._subscribed_channels[ws].add(channel)

    async def broadcast(self, channel: str, data: dict) -> None:
        """向订阅了某频道的所有连接广播"""
        payload = json.dumps({
            "channel": channel,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, default=str, ensure_ascii=False)

        dead = []
        for ws in self._connections:
            try:
                if channel in self._subscribed_channels.get(ws, set()):
                    await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, channel: str, data: dict) -> None:
        """向单个连接发送"""
        payload = json.dumps({
            "channel": channel,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, default=str, ensure_ascii=False)

        try:
            await ws.send_text(payload)
        except Exception:
            self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


# 全局单例
manager = ConnectionManager()


# ============================================================================
# 推送辅助函数
# ============================================================================

async def push_account_update(account_data: dict) -> None:
    """推送账户更新"""
    await manager.broadcast("account", account_data)


async def push_position_update(positions: dict) -> None:
    """推送持仓更新"""
    await manager.broadcast("positions", positions)


async def push_trade_update(fill_data: dict) -> None:
    """推送成交通知"""
    await manager.broadcast("trade", fill_data)


async def push_alert(message: str, level: str = "info") -> None:
    """推送告警"""
    await manager.broadcast("alert", {"message": message, "level": level})
