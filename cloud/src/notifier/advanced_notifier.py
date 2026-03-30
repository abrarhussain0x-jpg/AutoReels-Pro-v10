"""AutoReels Pro v10 — Advanced Multi-Channel Notification System"""

from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from jinja2 import Template
import asyncio

logger = logging.getLogger(__name__)

class NotificationLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class NotificationChannel(str, Enum):
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"

@dataclass
class Notification:
    """Single notification event"""
    title: str
    message: str
    level: NotificationLevel
    channels: List[NotificationChannel]
    tags: Dict[str, str] = None
    timestamp: datetime = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.tags is None:
            self.tags = {}
        if self.metadata is None:
            self.metadata = {}

class NotificationTemplate:
    """Notification templates with Jinja2 rendering"""
    
    templates = {
        'video_queued': """
🎬 New Video Queued
Title: {{ title }}
Channel: {{ channel }}
Duration: {{ duration_minutes }}m
Status: Queued for processing
        """,
        'processing_complete': """
✅ Video Processing Complete
Title: {{ title }}
Clips Generated: {{ clip_count }}
Total Duration: {{ total_duration }}m
Avg Quality Score: {{ avg_quality_score }}/100
        """,
        'upload_successful': """
📤 Upload Successful
Platform: {{ platform }}
Post ID: {{ post_id }}
Posted At: {{ posted_at }}
Caption: {{ caption }}
        """,
        'viral_detected': """
🚀 VIRAL ALERT!
Platform: {{ platform }}
Views: {{ views:,d }}
Engagement Rate: {{ engagement_rate:.1%}}
Velocity: {{ velocity }}/hour
Recommendation: {{ recommendation }}
        """,
        'upload_failed': """
❌ Upload Failed
Platform: {{ platform }}
Video: {{ video_title }}
Error: {{ error_message }}
Retry: Scheduled for {{ retry_time }}
        """,
        'negative_sentiment': """
⚠️  Negative Sentiment Detected
Video: {{ video_title }}
Platform: {{ platform }}
Negative Comments: {{ negative_count }}
Positive: {{ positive_count }}
Recommendation: {{ recommendation }}
        """,
        'performance_report': """
📊 Weekly Performance Report
Period: {{ period }}
Total Videos: {{ total_videos }}
Total Views: {{ total_views:,d }}
Avg Engagement: {{ avg_engagement:.1%}}
Top Platform: {{ top_platform }}
Best Performing Clip: {{ top_clip }}
        """
    }
    
    @classmethod
    def render(cls, template_name: str, context: dict) -> str:
        """Render template with context"""
        if template_name not in cls.templates:
            return ""
        template_str = cls.templates[template_name]
        template = Template(template_str)
        return template.render(**context)

class AdvancedNotificationSystem:
    """
    10x more real: Multi-channel notification routing.
    - Sends to Slack, Discord, Telegram, Email simultaneously
    - Intelligent throttling (no spam)
    - Template-based messages
    - Delivery tracking
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.notification_history = []
        self.throttle_cache = {}  # Prevent duplicate notifications
    
    async def send(self, notification: Notification) -> Dict[str, bool]:
        """Send notification to all configured channels"""
        results = {}
        
        for channel in notification.channels:
            try:
                if channel == NotificationChannel.SLACK:
                    await self._send_slack(notification)
                    results[channel] = True
                elif channel == NotificationChannel.DISCORD:
                    await self._send_discord(notification)
                    results[channel] = True
                elif channel == NotificationChannel.TELEGRAM:
                    await self._send_telegram(notification)
                    results[channel] = True
                elif channel == NotificationChannel.EMAIL:
                    await self._send_email(notification)
                    results[channel] = True
                elif channel == NotificationChannel.WEBHOOK:
                    await self._send_webhook(notification)
                    results[channel] = True
            except Exception as e:
                logger.error(f"Failed to send via {channel}: {e}")
                results[channel] = False
        
        # Record in history
        self.notification_history.append({
            'notification': notification,
            'results': results,
            'sent_at': datetime.utcnow()
        })
        
        return results
    
    async def _send_slack(self, notification: Notification):
        """Send to Slack with formatted blocks"""
        import aiohttp
        
        webhook_url = self.config.get('slack_webhook')
        if not webhook_url:
            return
        
        # Color based on level
        colors = {
            NotificationLevel.INFO: '#439FE0',
            NotificationLevel.SUCCESS: '#36C5F0',
            NotificationLevel.WARNING: '#F2C94C',
            NotificationLevel.ERROR: '#E92C2C',
            NotificationLevel.CRITICAL: '#C92A2A'
        }
        
        payload = {
            'blocks': [
                {
                    'type': 'header',
                    'text': {
                        'type': 'plain_text',
                        'text': notification.title,
                        'emoji': True
                    }
                },
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': notification.message
                    }
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': f"*Level:* {notification.level.value.upper()} | *Time:* {notification.timestamp.isoformat()}"
                        }
                    ]
                }
            ],
            'attachments': [
                {
                    'color': colors.get(notification.level, '#808080'),
                    'blocks': []
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Slack webhook failed: {resp.status}")
    
    async def _send_discord(self, notification: Notification):
        """Send to Discord with embeds"""
        import aiohttp
        
        webhook_url = self.config.get('discord_webhook')
        if not webhook_url:
            return
        
        colors = {
            NotificationLevel.INFO: 0x439FE0,
            NotificationLevel.SUCCESS: 0x36C5F0,
            NotificationLevel.WARNING: 0xF2C94C,
            NotificationLevel.ERROR: 0xE92C2C,
            NotificationLevel.CRITICAL: 0xC92A2A
        }
        
        payload = {
            'username': 'AutoReels Pro',
            'embeds': [
                {
                    'title': notification.title,
                    'description': notification.message,
                    'color': colors.get(notification.level, 808080),
                    'fields': [
                        {
                            'name': 'Level',
                            'value': notification.level.value.upper(),
                            'inline': True
                        },
                        {
                            'name': 'Time',
                            'value': notification.timestamp.isoformat(),
                            'inline': True
                        }
                    ],
                    'footer': {
                        'text': 'AutoReels Pro v10'
                    }
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status != 204:
                    logger.error(f"Discord webhook failed: {resp.status}")
    
    async def _send_telegram(self, notification: Notification):
        """Send to Telegram"""
        import aiohttp
        
        token = self.config.get('telegram_token')
        chat_id = self.config.get('telegram_chat_id')
        
        if not token or not chat_id:
            return
        
        emoji = {
            NotificationLevel.INFO: 'ℹ️',
            NotificationLevel.SUCCESS: '✅',
            NotificationLevel.WARNING: '⚠️',
            NotificationLevel.ERROR: '❌',
            NotificationLevel.CRITICAL: '🚨'
        }.get(notification.level, '📢')
        
        text = f"{emoji} *{notification.title}*\n\n{notification.message}"
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Telegram failed: {resp.status}")
    
    async def _send_email(self, notification: Notification):
        """Send via SMTP"""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        smtp_host = self.config.get('email_smtp')
        email_from = self.config.get('email_from')
        email_password = self.config.get('email_password')
        email_to = self.config.get('email_to', [email_from])
        
        if not all([smtp_host, email_from, email_password]):
            return
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = notification.title
        msg['From'] = email_from
        msg['To'] = ','.join(email_to) if isinstance(email_to, list) else email_to
        
        # HTML body
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #333;">{notification.title}</h2>
                <p>{notification.message}</p>
                <hr>
                <p style="color: #999; font-size: 12px;">
                    Level: <strong>{notification.level.value.upper()}</strong><br>
                    Time: {notification.timestamp.isoformat()}
                </p>
            </body>
        </html>
        """
        
        part = MIMEText(html, 'html')
        msg.attach(part)
        
        try:
            with smtplib.SMTP(smtp_host, 587) as server:
                server.starttls()
                server.login(email_from, email_password)
                server.sendmail(email_from, email_to if isinstance(email_to, list) else [email_to], msg.as_string())
        except Exception as e:
            logger.error(f"Email send failed: {e}")
    
    async def _send_webhook(self, notification: Notification):
        """Send to custom webhook"""
        import aiohttp
        
        webhook_url = notification.metadata.get('webhook_url')
        if not webhook_url:
            return
        
        payload = {
            'title': notification.title,
            'message': notification.message,
            'level': notification.level.value,
            'tags': notification.tags,
            'timestamp': notification.timestamp.isoformat()
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Webhook failed: {resp.status}")
    
    def throttle(self, key: str, seconds: int = 300) -> bool:
        """Prevent duplicate notifications within time window"""
        now = datetime.utcnow()
        if key in self.throttle_cache:
            last_sent = self.throttle_cache[key]
            if (now - last_sent).total_seconds() < seconds:
                return False  # Throttled
        
        self.throttle_cache[key] = now
        return True  # OK to send
    
    def get_history(self, hours: int = 24) -> List[dict]:
        """Get notification history"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return [
            n for n in self.notification_history
            if n['sent_at'] >= cutoff
        ]

    def send_sync(self, notification: "Notification") -> dict:
        """Synchronous wrapper — fire-and-forget for use in non-async pipeline code."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.send(notification))
                return {}
            return loop.run_until_complete(self.send(notification))
        except Exception as e:
            logger.warning("Notification send_sync failed: %s", e)
            return {}

# Example usage in tasks.py:
"""
@app.task
def notify_viral_video(upload_id: str, metrics: dict):
    from src.notifier.advanced_notifier import (
        AdvancedNotificationSystem, Notification, NotificationLevel, NotificationChannel,
        NotificationTemplate
    )
    from src.config import get_settings
    
    settings = get_settings()
    notifier = AdvancedNotificationSystem(settings.notifications.dict())
    
    # Check if already notified recently
    if not notifier.throttle(f"viral_{upload_id}", seconds=3600):
        return  # Already notified in last hour
    
    # Render template
    message = NotificationTemplate.render('viral_detected', {
        'platform': metrics['platform'],
        'views': metrics['views'],
        'engagement_rate': metrics['engagement_rate'],
        'velocity': f"{metrics['velocity']:.0f} views/hour",
        'recommendation': 'Promote to all platforms'
    })
    
    notification = Notification(
        title=f"🚀 Viral Video Detected!",
        message=message,
        level=NotificationLevel.SUCCESS,
        channels=[
            NotificationChannel.SLACK,
            NotificationChannel.DISCORD,
            NotificationChannel.TELEGRAM
        ],
        tags={'upload_id': upload_id, 'type': 'viral_alert'}
    )
    
    # Send async
    asyncio.create_task(notifier.send(notification))
"""
