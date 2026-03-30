"""
auto_reply.py — Automated comment reply engine.

Replies to comments on your Facebook posts to:
  1. Boost engagement velocity (FB rewards active comment sections)
  2. Answer common questions automatically
  3. Drive viewers to follow / watch Part N
  4. Keep the conversation alive (each reply = algorithm notification)

Reply strategy:
  - Reply to ALL comments within first 2 hours (biggest algorithmic impact)
  - Use varied, natural-sounding templates (not robotic)
  - Always include a soft CTA to follow or watch next part
  - Heart/like every comment automatically

Zero cost. Uses Facebook Graph API only.
"""
from __future__ import annotations
import json, logging, random, time, urllib.parse, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"

# Natural reply templates - varied to avoid spam detection
REPLY_TEMPLATES = {
    "positive": [
        "😭 RIGHT?! Part {next} is even more intense — follow so you don't miss it! 🔥",
        "🔥 Glad you're watching! Part {next} drops soon — follow {channel}!",
        "❤️ Thank you! The story gets WILD from here 👀 Follow for Part {next}!",
        "🙌 Same! This part got me too 😭 Part {next} is already up on our page!",
        "💯 Right?! Stay tuned — Part {next} hits DIFFERENT 🎬 Follow {channel}!",
    ],
    "question": [
        "🎬 Great question! Watch Part {next} — it explains everything! Follow {channel}!",
        "👀 Keep watching! Part {next} answers that exact question 🔥 Follow us!",
        "💡 You'll find out in Part {next}! Make sure you're following {channel}!",
        "🤔 Such a good question! Part {next} reveals everything — follow {channel}!",
    ],
    "neutral": [
        "🔥 Part {next} is even better — follow {channel} so you don't miss it!",
        "👀 Just wait for Part {next}... follow {channel} to see what happens!",
        "🎬 Stay tuned! Part {next} drops soon on {channel} — follow us! ❤️",
        "💬 Thanks for watching! Part {next} is going to blow your mind 🤯 Follow!",
    ],
    "negative": [
        "😅 We hear you! The story gets better — give Part {next} a chance! 🙏",
        "🙏 Thanks for the feedback! Part {next} might change your mind 👀",
        "💪 Fair point! But Part {next} has a totally different vibe — follow to see!",
    ],
}


@dataclass
class ReplyJob:
    comment_id: str
    comment_text: str
    post_id: str
    author: str = ""


class AutoReplyBot:
    """
    Automatically replies to comments on Facebook posts.
    Prioritizes first 2 hours (highest algorithmic impact).
    """

    def __init__(
        self,
        page_id: str,
        access_token: str,
        channel_name: str = "AutoReels",
        max_replies_per_post: int = 20,
        reply_delay_s: int = 30,
        enabled: bool = True,
    ):
        self.page_id    = page_id
        self.token      = access_token
        self.channel    = channel_name
        self.max_replies = max_replies_per_post
        self.delay      = reply_delay_s
        self.enabled    = enabled
        self._replied   = set()   # track already-replied comment IDs in memory

    def is_configured(self) -> bool:
        return bool(self.page_id and self.token
                    and not self.token.startswith("${"))

    def reply_to_post(self, post_id: str, next_part: int) -> int:
        """Fetch and reply to all unreplied comments on a post. Returns count."""
        if not self.enabled or not self.is_configured():
            return 0

        comments = self._fetch_comments(post_id)
        if not comments:
            return 0

        replied = 0
        for comment in comments[:self.max_replies]:
            cid = comment.get("id", "")
            if cid in self._replied:
                continue

            text = comment.get("message", "")
            if not text:
                continue

            sentiment = self._classify_simple(text)
            reply     = self._pick_reply(sentiment, next_part)

            if self._post_reply(cid, reply):
                self._like_comment(cid)
                self._replied.add(cid)
                replied += 1
                log.info("[AutoReply] replied to %s (%s)", cid[:15], sentiment)
                time.sleep(self.delay)   # avoid rate limit

        return replied

    def _fetch_comments(self, post_id: str) -> List[dict]:
        url = (f"{GRAPH}/{post_id}/comments"
               f"?fields=id,message,from&limit=50"
               f"&filter=toplevel&order=ranked"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            return data.get("data", [])
        except Exception as e:
            log.debug("[AutoReply] fetch comments error: %s", e)
            return []

    def _classify_simple(self, text: str) -> str:
        """Quick rule-based sentiment (no API needed)."""
        text_lower = text.lower()
        pos_words  = ["love","great","amazing","good","wow","fire","🔥","❤️","😍","best"]
        neg_words  = ["bad","boring","hate","worst","skip","waste","dislike","😒","👎"]
        q_words    = ["?","what","why","how","who","when","where"]

        if any(w in text_lower for w in q_words):
            return "question"
        if any(w in text_lower for w in neg_words):
            return "negative"
        if any(w in text_lower for w in pos_words):
            return "positive"
        return "neutral"

    def _pick_reply(self, sentiment: str, next_part: int) -> str:
        pool = REPLY_TEMPLATES.get(sentiment, REPLY_TEMPLATES["neutral"])
        tpl  = random.choice(pool)
        return tpl.format(channel=self.channel, next=next_part)

    def _post_reply(self, comment_id: str, message: str) -> bool:
        url  = f"{GRAPH}/{comment_id}/comments"
        data = urllib.parse.urlencode({
            "message": message[:500],
            "access_token": self.token,
        }).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            return "id" in result
        except Exception as e:
            log.debug("[AutoReply] post reply error: %s", e)
            return False

    def _like_comment(self, comment_id: str) -> bool:
        """Like/heart a comment (increases engagement signal)."""
        url  = f"{GRAPH}/{comment_id}/likes"
        data = urllib.parse.urlencode({"access_token": self.token}).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10):
                pass
            return True
        except Exception:
            return False
