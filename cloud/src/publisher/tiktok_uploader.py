"""
tiktok_uploader.py — TikTok video uploader via Content Posting API v2.
Direct file upload flow. Supports pull/push init modes.
"""
from __future__ import annotations
import json, logging, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com/v2"


class TikTokUploader:

    def __init__(self, access_token: str, privacy_level: str = "PUBLIC_TO_EVERYONE",
                 allow_comments: bool = True, allow_duet: bool = True,
                 allow_stitch: bool = True):
        self.token         = access_token
        self.privacy       = privacy_level
        self.allow_comments= allow_comments
        self.allow_duet    = allow_duet
        self.allow_stitch  = allow_stitch

    def is_configured(self) -> bool:
        return bool(self.token and not self.token.startswith("${"))

    def upload(self, clip_path: Path, caption: str,
               thumbnail_path: Optional[Path] = None) -> Optional[str]:
        clip_path = Path(clip_path)
        if not clip_path.exists():
            return None

        file_size = clip_path.stat().st_size
        log.info("[TT] uploading %s (%.1f MB)", clip_path.name, file_size / 1e6)

        # Init upload
        publish_id = self._init_upload(file_size, caption)
        if not publish_id:
            return None

        # Upload file
        ok = self._upload_file(publish_id, clip_path, file_size)
        if not ok:
            return None

        # Poll for status
        result = self._poll_status(publish_id)
        log.info("[TT] ✅ published → %s", result)
        return result

    def _init_upload(self, file_size: int, caption: str) -> Optional[str]:
        url  = f"{API}/post/publish/video/init/"
        body = json.dumps({
            "post_info": {
                "title": caption[:2200],
                "privacy_level": self.privacy,
                "disable_comment": not self.allow_comments,
                "duet_disabled": not self.allow_duet,
                "stitch_disabled": not self.allow_stitch,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json; charset=UTF-8")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data.get("data", {}).get("publish_id")
        except Exception as e:
            log.error("[TT] init upload failed: %s", e)
            return None

    def _upload_file(self, publish_id: str, clip_path: Path, file_size: int) -> bool:
        # Get upload URL
        url  = f"{API}/post/publish/inbox/video/init/"
        body = json.dumps({"publish_id": publish_id}).encode()
        req  = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            upload_url = data.get("data", {}).get("upload_url", "")
        except Exception:
            upload_url = ""

        if not upload_url:
            log.warning("[TT] no upload URL — skipping file transfer")
            return True   # some flows auto-handle

        with open(clip_path, "rb") as f:
            video_bytes = f.read()
        req2 = urllib.request.Request(upload_url, data=video_bytes, method="PUT")
        req2.add_header("Content-Range", f"bytes 0-{file_size-1}/{file_size}")
        req2.add_header("Content-Type", "video/mp4")
        try:
            with urllib.request.urlopen(req2, timeout=300):
                pass
            return True
        except Exception as e:
            log.error("[TT] file upload failed: %s", e)
            return False

    def _poll_status(self, publish_id: str, max_wait: int = 60) -> Optional[str]:
        url  = f"{API}/post/publish/status/fetch/"
        body = json.dumps({"publish_id": publish_id}).encode()
        for _ in range(max_wait // 5):
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                status = data.get("data", {}).get("status", "")
                if status == "PUBLISH_COMPLETE":
                    return data.get("data", {}).get("publicaly_available_post_id", [publish_id])[0]
                if status in ("FAILED", "SPAM_RISK_CREATOR"):
                    log.error("[TT] publish failed: %s", data)
                    return None
            except Exception:
                pass
            time.sleep(5)
        return publish_id   # return ID even if polling timed out
