"""
instagram_uploader.py — Real Instagram Reels uploader via Graph API.
Uses the two-step: create container → publish flow.
Requires a publicly accessible video URL (uploads to FB CDN first).
"""
from __future__ import annotations
import json, logging, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"


class InstagramUploader:

    def __init__(self, ig_user_id: str, access_token: str, share_to_feed: bool = True):
        self.user_id       = ig_user_id
        self.token         = access_token
        self.share_to_feed = share_to_feed

    def is_configured(self) -> bool:
        return bool(self.user_id and self.token
                    and not self.user_id.startswith("${")
                    and not self.token.startswith("${"))

    def upload(self, video_url: str, caption: str,
               thumbnail_url: str = "") -> Optional[str]:
        """
        Upload a Reel. video_url must be publicly accessible (CDN/S3 URL).
        Returns media_id on success, None on failure.
        """
        if not video_url.startswith("http"):
            log.error("[IG] video_url must be a public URL, got: %s", video_url[:50])
            return None

        log.info("[IG] creating Reel container for %s", video_url[:60])

        # Step 1: Create media container
        container_id = self._create_container(video_url, caption, thumbnail_url)
        if not container_id:
            return None

        # Step 2: Wait for container to process (poll up to 5 min)
        ready = self._wait_for_ready(container_id, max_wait=300)
        if not ready:
            log.error("[IG] container never became ready: %s", container_id)
            return None

        # Step 3: Publish
        media_id = self._publish(container_id)
        if media_id:
            log.info("[IG] ✅ published → media_id=%s", media_id)
        return media_id

    def _create_container(self, video_url, caption, thumbnail_url) -> Optional[str]:
        params = {
            "media_type":    "REELS",
            "video_url":     video_url,
            "caption":       caption[:2200],
            "share_to_feed": "true" if self.share_to_feed else "false",
            "access_token":  self.token,
        }
        if thumbnail_url:
            params["thumb_offset"] = "0"

        url  = f"{GRAPH}/{self.user_id}/media"
        data = urllib.parse.urlencode(params).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            cid = result.get("id")
            log.debug("[IG] container created: %s", cid)
            return cid
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            log.error("[IG] create container error %d: %s", e.code, body)
            if e.code in (401, 403):
                raise PermissionError(f"IG auth error {e.code}")
            return None
        except Exception as e:
            log.error("[IG] create container exception: %s", e)
            return None

    def _wait_for_ready(self, container_id: str, max_wait: int = 300) -> bool:
        url = (f"{GRAPH}/{container_id}"
               f"?fields=status_code,status&access_token={self.token}")
        for attempt in range(max_wait // 10):
            time.sleep(10)
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = json.loads(resp.read())
                status = data.get("status_code", "")
                log.debug("[IG] container status: %s (attempt %d)", status, attempt + 1)
                if status == "FINISHED":
                    return True
                if status in ("ERROR", "EXPIRED"):
                    log.error("[IG] container failed: %s", data.get("status"))
                    return False
            except Exception as e:
                log.debug("[IG] status poll error: %s", e)
        return False

    def _publish(self, container_id: str) -> Optional[str]:
        url    = f"{GRAPH}/{self.user_id}/media_publish"
        params = {"creation_id": container_id, "access_token": self.token}
        data   = urllib.parse.urlencode(params).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            return result.get("id")
        except Exception as e:
            log.error("[IG] publish error: %s", e)
            return None

    def get_metrics(self, media_id: str) -> dict:
        url = (f"{GRAPH}/{media_id}/insights"
               f"?metric=plays,reach,likes,comments,shares"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            metrics = {}
            for item in data.get("data", []):
                metrics[item["name"]] = item.get("values", [{}])[-1].get("value", 0)
            return metrics
        except Exception as e:
            log.debug("[IG] metrics fetch failed: %s", e)
            return {}
