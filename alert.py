"""
告警通知模块

支持多渠道告警：
- 钉钉机器人
- 企业微信机器人
- 邮件通知（预留）
- 控制台日志

告警级别:
- info: 普通信息
- warning: 警告
- critical: 严重（需要立即关注）
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Optional, Callable

import requests

logger = logging.getLogger(__name__)


class AlertLevel:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert:
    """单条告警"""

    def __init__(self, message: str, level: str = AlertLevel.INFO, title: str = ""):
        self.message = message
        self.level = level
        self.title = title or level.upper()
        self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "message": self.message,
            "level": self.level,
            "timestamp": self.timestamp.isoformat(),
        }


class AlertChannel:
    """告警渠道基类"""

    name: str = "base"

    def send(self, alert: Alert) -> bool:
        """发送告警，返回是否成功"""
        raise NotImplementedError


# ============================================================================
# 钉钉机器人
# ============================================================================

class DingTalkChannel(AlertChannel):
    """
    钉钉机器人通知。

    配置:
        1. 创建钉钉群机器人
        2. 获取 Webhook URL
        3. 设置安全关键词: "量化交易"

    支持:
        - 文本消息
        - Markdown 消息
        - @所有人 (critical级别)
    """

    name = "dingtalk"

    def __init__(self, webhook_url: str, secret: str = ""):
        self._webhook_url = webhook_url
        self._secret = secret

    def send(self, alert: Alert) -> bool:
        """发送钉钉消息"""
        try:
            # 根据级别选择图标
            icons = {
                AlertLevel.INFO: "📊",
                AlertLevel.WARNING: "⚠️",
                AlertLevel.CRITICAL: "🚨",
            }
            icon = icons.get(alert.level, "📊")

            # Markdown 格式
            markdown_text = f"""## {icon} {alert.title}

{alert.message}

---
*时间: {alert.timestamp.strftime("%Y-%m-%d %H:%M:%S")}*
*级别: {alert.level}*"""

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[{alert.level}] {alert.title}",
                    "text": markdown_text,
                },
            }

            # 严重告警时 @所有人
            if alert.level == AlertLevel.CRITICAL:
                payload["at"] = {"isAtAll": True}

            # 如果有secret，需要加签（时间戳+签名）
            if self._secret:
                payload = self._sign(payload)

            resp = requests.post(
                self._webhook_url,
                json=payload,
                timeout=5,
            )
            result = resp.json()

            if result.get("errcode") == 0:
                logger.info(f"钉钉告警发送成功: {alert.title}")
                return True
            else:
                logger.error(f"钉钉告警失败: {result}")
                return False

        except Exception:
            logger.exception("钉钉告警异常")
            return False

    def _sign(self, payload: dict) -> dict:
        """钉钉加签（如需要）"""
        import time
        import hmac
        import hashlib
        import base64
        import urllib.parse

        timestamp = str(round(time.time() * 1000))
        secret_enc = self._secret.encode("utf-8")
        string_to_sign = f"{timestamp}\n{self._secret}"
        string_to_sign_enc = string_to_sign.encode("utf-8")
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

        # 拼接签名到URL
        if "?" in self._webhook_url:
            self._webhook_url = f"{self._webhook_url}&timestamp={timestamp}&sign={sign}"
        else:
            self._webhook_url = f"{self._webhook_url}?timestamp={timestamp}&sign={sign}"

        return payload


# ============================================================================
# 企业微信机器人
# ============================================================================

class WeChatWorkChannel(AlertChannel):
    """
    企业微信机器人通知。

    配置:
        1. 企业微信群 → 群机器人 → 添加
        2. 获取 Webhook URL
    """

    name = "wechat_work"

    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        try:
            icons = {
                AlertLevel.INFO: "📊",
                AlertLevel.WARNING: "⚠️",
                AlertLevel.CRITICAL: "🚨",
            }
            icon = icons.get(alert.level, "📊")

            content = f"{icon} **{alert.title}**\n{alert.message}\n> 时间: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }

            resp = requests.post(self._webhook_url, json=payload, timeout=5)
            result = resp.json()

            return result.get("errcode") == 0

        except Exception:
            logger.exception("企业微信告警异常")
            return False


# ============================================================================
# 控制台日志
# ============================================================================

class ConsoleChannel(AlertChannel):
    """控制台日志输出（开发调试用）"""

    name = "console"

    def send(self, alert: Alert) -> bool:
        icons = {"info": "📊", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(alert.level, "")
        print(f"{icon} [{alert.level.upper()}] {alert.title}: {alert.message}")
        return True


# ============================================================================
# 告警管理器
# ============================================================================

class AlertManager:
    """
    告警管理器 — 统一的多渠道告警分发。

    使用方式:
        am = AlertManager()
        am.add_channel(DingTalkChannel(webhook_url="..."))
        am.add_channel(WeChatWorkChannel(webhook_url="..."))

        am.info("策略启动", "双均线策略已开始运行")
        am.warning("回撤告警", "当前回撤已达 8%")
        am.critical("止损触发", "000001.SZ 触发硬止损，立即平仓")

    限频: 同一级别的告警在 cool_down 秒内不会重复发送。
    """

    def __init__(self, cool_down_seconds: int = 60):
        self._channels: list[AlertChannel] = []
        self._cool_down = cool_down_seconds
        self._last_send: dict[str, datetime] = {}  # (level, title) → last_send_time
        self._lock = threading.Lock()

        # 历史记录（内存中保留最近100条）
        self._history: list[Alert] = []
        self._max_history = 100

    def add_channel(self, channel: AlertChannel) -> "AlertManager":
        self._channels.append(channel)
        logger.info(f"添加告警渠道: {channel.name}")
        return self

    def remove_channel(self, name: str) -> None:
        self._channels = [c for c in self._channels if c.name != name]

    # ------------------------------------------------------------------
    # 快捷方法
    # ------------------------------------------------------------------

    def info(self, title: str, message: str = "") -> None:
        self.send(Alert(message, AlertLevel.INFO, title))

    def warning(self, title: str, message: str = "") -> None:
        self.send(Alert(message, AlertLevel.WARNING, title))

    def critical(self, title: str, message: str = "") -> None:
        self.send(Alert(message, AlertLevel.CRITICAL, title))

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    def send(self, alert: Alert) -> None:
        """发送告警（异步、去重）"""
        # 去重检查
        key = f"{alert.level}_{alert.title}"
        now = datetime.now()

        with self._lock:
            last = self._last_send.get(key)
            if last and (now - last).total_seconds() < self._cool_down:
                logger.debug(f"告警限频跳过: {key}")
                return
            self._last_send[key] = now

        # 记录历史
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # 异步发送到所有渠道
        for channel in self._channels:
            t = threading.Thread(
                target=self._send_to_channel,
                args=(channel, alert),
                daemon=True,
            )
            t.start()

    def _send_to_channel(self, channel: AlertChannel, alert: Alert) -> None:
        try:
            success = channel.send(alert)
            if not success:
                logger.warning(f"告警渠道 {channel.name} 发送失败")
        except Exception:
            logger.exception(f"告警渠道 {channel.name} 异常")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_history(self, level: Optional[str] = None, limit: int = 50) -> list[dict]:
        """获取告警历史"""
        alerts = self._history
        if level:
            alerts = [a for a in alerts if a.level == level]
        return [a.to_dict() for a in alerts[-limit:]]

    @property
    def channels(self) -> list[str]:
        return [c.name for c in self._channels]


# ============================================================================
# 全局单例
# ============================================================================

_global_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器单例"""
    global _global_alert_manager
    if _global_alert_manager is None:
        _global_alert_manager = AlertManager()
        # 默认添加控制台渠道
        _global_alert_manager.add_channel(ConsoleChannel())
    return _global_alert_manager


def setup_alerts(config: dict) -> AlertManager:
    """根据配置初始化告警"""
    am = get_alert_manager()

    # 钉钉
    dingtalk_url = config.get("dingtalk_webhook", "")
    if dingtalk_url:
        dingtalk_secret = config.get("dingtalk_secret", "")
        am.add_channel(DingTalkChannel(dingtalk_url, dingtalk_secret))
        logger.info("钉钉告警已配置")

    # 企业微信
    wechat_url = config.get("wechat_webhook", "")
    if wechat_url:
        am.add_channel(WeChatWorkChannel(wechat_url))
        logger.info("企业微信告警已配置")

    return am
