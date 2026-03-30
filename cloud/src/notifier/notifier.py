"""
notifier.py v10.0 — Multi-channel notification dispatcher.

Sends alerts to Telegram, Discord, Slack, and Email.
Used by RetryEngine, CommentBot, and VelocityTracker for critical alerts.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger(__name__)


class Notifier:
    """Dispatches messages to all configured notification channels."""

    def __init__(self, config: dict) -> None:
        notif = config.get("notifications", {})
        self._telegram = notif.get("telegram", {})
        self._discord  = notif.get("discord", {})
        self._slack    = notif.get("slack", {})
        self._email    = notif.get("email", {})

    def send(self, message: str) -> None:
        """Send message to all configured channels."""
        self._send_telegram(message)
        self._send_discord(message)
        self._send_slack(message)

    def _send_telegram(self, message: str) -> None:
        token   = self._telegram.get("token", "")
        chat_id = self._telegram.get("chat_id", "")
        if not token or not chat_id or token.startswith("${"):
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message[:4096],
            "parse_mode": "HTML",
        }).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=data, method="POST"), timeout=10
            ):
                pass
        except Exception as exc:
            log.debug("[Notifier] Telegram failed: %s", exc)

    def _send_discord(self, message: str) -> None:
        webhook = self._discord.get("webhook_url", "")
        if not webhook or webhook.startswith("${"):
            return
        body = json.dumps({"content": message[:2000]}).encode()
        try:
            req = urllib.request.Request(
                webhook, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            log.debug("[Notifier] Discord failed: %s", exc)

    def _send_slack(self, message: str) -> None:
        webhook = self._slack.get("webhook_url", "")
        if not webhook or webhook.startswith("${"):
            return
        body = json.dumps({"text": message[:3000]}).encode()
        try:
            req = urllib.request.Request(
                webhook, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            log.debug("[Notifier] Slack failed: %s", exc)
