"""
first_comment.py — Auto-post first comment immediately after upload.
Facebook's algorithm gives a strong boost to posts with early comments.
Posting the first comment within 60 seconds of upload is a proven tactic.
Also supports pinning the comment for maximum visibility.
"""
from __future__ import annotations
import json, logging, time, urllib.parse, urllib.request
from typing import Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"


class FirstCommentPoster:
    """Posts and pins the first comment on every uploaded Reel."""

    def __init__(self, page_id: str, access_token: str):
        self.page_id = page_id
        self.token   = access_token

    def is_configured(self) -> bool:
        return bool(self.page_id and self.token
                    and not self.token.startswith("${"))

    def post_and_pin(
        self,
        post_id: str,
        comment_text: str,
        delay_seconds: int = 30,
    ) -> Optional[str]:
        """
        Wait delay_seconds then post + pin a comment.
        Returns comment_id or None.
        """
        if not self.is_configured():
            return None

        if delay_seconds > 0:
            log.info("[FirstComment] waiting %ds before posting...", delay_seconds)
            time.sleep(delay_seconds)

        comment_id = self._post_comment(post_id, comment_text)
        if comment_id:
            log.info("[FirstComment] ✅ posted comment %s", comment_id)
            self._pin_comment(post_id, comment_id)
        return comment_id

    def _post_comment(self, post_id: str, message: str) -> Optional[str]:
        url  = f"{GRAPH}/{post_id}/comments"
        data = urllib.parse.urlencode({
            "message":      message[:2000],
            "access_token": self.token,
        }).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            return result.get("id")
        except Exception as e:
            log.warning("[FirstComment] post failed: %s", e)
            return None

    def _pin_comment(self, post_id: str, comment_id: str) -> bool:
        """Pin comment to top (requires page token with full permissions)."""
        url  = f"{GRAPH}/{comment_id}"
        data = urllib.parse.urlencode({
            "is_hidden":    "false",
            "access_token": self.token,
        }).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10):
                pass
            log.debug("[FirstComment] pinned %s", comment_id)
            return True
        except Exception as e:
            log.debug("[FirstComment] pin failed (ok): %s", e)
            return False
