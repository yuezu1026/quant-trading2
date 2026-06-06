"""
事件总线

负责模块间的解耦通信。所有模块通过发布/订阅事件来交互，
不直接调用对方的方法。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from .types import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], None]


class EventBus:
    """
    轻量级事件总线。

    使用方式:
        bus = EventBus()
        bus.register(EventType.BAR, my_handler)
        bus.emit(Event(type=EventType.BAR, data=bar))
        bus.unregister(EventType.BAR, my_handler)
    """

    def __init__(self):
        self._handlers: dict[EventType, list[Handler]] = defaultdict(list)
        self._event_count: dict[EventType, int] = defaultdict(int)

    def register(self, event_type: EventType, handler: Handler) -> None:
        """注册事件处理器"""
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(f"注册处理器: {event_type.value} -> {handler.__name__}")

    def unregister(self, event_type: EventType, handler: Handler) -> None:
        """注销事件处理器"""
        try:
            self._handlers[event_type].remove(handler)
            logger.debug(f"注销处理器: {event_type.value} -> {handler.__name__}")
        except ValueError:
            pass

    def emit(self, event: Event, *, priority: int = 0) -> None:
        """
        发布事件，通知所有注册的处理器。

        priority 暂不支持，保留给未来扩展（优先级队列）。
        """
        handlers = self._handlers.get(event.type, [])
        self._event_count[event.type] += 1

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    f"事件处理器异常: {event.type.value} -> {handler.__name__}"
                )

    def emit_batch(self, events: list[Event]) -> None:
        """批量发布事件"""
        for event in events:
            self.emit(event)

    def handler_count(self, event_type: EventType) -> int:
        """返回某个事件类型的处理器数量"""
        return len(self._handlers.get(event_type, []))

    @property
    def stats(self) -> dict:
        """返回事件统计信息"""
        return {k.value: v for k, v in self._event_count.items()}

    def clear(self) -> None:
        """清空所有处理器（用于测试/重置）"""
        self._handlers.clear()
        self._event_count.clear()
