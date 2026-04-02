"""
facebook_uploader.py — Real Facebook Reels uploader via Graph API v19.
Handles resumable video upload (required for files >10MB).
Supports multiple accounts via AccountRotator.
"""
from __future__ import annotations
import json, logging, mimetypes, os, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

FB_API_VERSION = os.getenv("FB_API_VERSION", "v19.0")
GRAPH = f"https://graph.facebook.com/{FB_API_VERSION}"


class FacebookUploader:
    """Uploads video clips as Facebook Reels using the Graph API."""

    def __init__(self, page_id: str, access_token: str,
                 published: bool = True, upload_as_reel: bool = True):
        self.page_id    = page_id
        self.token      = access_token
        self.published  = published
        self.as_reel    = upload_as_reel

    def is_configured(self) -> bool:
        return bool(self.page_id and self.token
                    and not self.page_id.startswith("${")
                    and not self.token.startswith("${"))

    def upload(self, clip_path: Path, caption: str,
               thumbnail_path: Optional[Path] = None) -> Optional[str]:
        """Upload a video clip. Returns post_id or None on failure."""
        clip_path = Path(clip_path)
        if not clip_path.exists():
            log.error("[FB] clip not found: %s", clip_path)
            return None

        file_size = clip_path.stat().st_size
        log.info("[FB] uploading %s (%.1f MB) to page %s",
                 clip_path.name, file_size / 1e6, self.page_id)

        # Step 1: Initialize upload session
        session = self._init_upload(file_size, clip_path.name)
        if not session:
            return None

        upload_session_id = session.get("upload_session_id") or session.get("id")
        video_id          = session.get("video_id")
        
        # Validate required fields from session response
        if not upload_session_id or not video_id:
            log.error("[FB] session init missing fields: upload_session_id=%s, video_id=%s",
                      upload_session_id, video_id)
            return None

        # Step 2: Upload file bytes (chunked for large files)
        success = self._transfer_file(upload_session_id, clip_path)
        if not success:
            log.error("[FB] file transfer failed")
            return None

        # Step 3: Finalize / publish
        post_id = self._finalize(video_id, caption, thumbnail_path)
        if post_id:
            log.info("[FB] ✅ uploaded → post_id=%s", post_id)
        return post_id

    # ── Graph API Steps ──────────────────────────────────────────────────────

    def _init_upload(self, file_size: int, filename: str) -> Optional[dict]:
        """POST /{page_id}/video_reels — initialize upload session."""
        params = {
            "upload_phase": "start",
            "access_token": self.token,
            "file_size": str(file_size),
        }
        url = f"{GRAPH}/{self.page_id}/video_reels"
        data = urllib.parse.urlencode(params).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            log.debug("[FB] init upload: %s", result)
            return result
        except Exception as e:
            log.error("[FB] init upload failed: %s", e)
            return None

    def _transfer_file(self, upload_session_id: str, clip_path: Path) -> bool:
        """Transfer video bytes via Graph resumable upload."""
        if not upload_session_id:
            log.error("[FB] cannot transfer: upload_session_id is empty")
            return False
            
        file_size = clip_path.stat().st_size
        chunk_size = 10 * 1024 * 1024   # 10 MB chunks
        offset = 0

        with open(clip_path, "rb") as f:
            while offset < file_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break

                url = f"https://rupload.facebook.com/video-upload/{FB_API_VERSION}/{upload_session_id}"
                req = urllib.request.Request(url, data=chunk, method="POST")
                req.add_header("Authorization", f"OAuth {self.token}")
                req.add_header("offset", str(offset))
                req.add_header("file_size", str(file_size))
                req.add_header("Content-Type", "application/octet-stream")

                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        result = json.loads(resp.read())
                    if not result.get("success"):
                        log.error("[FB] chunk upload failed at offset %d: %s", offset, result)
                        return False
                    offset += len(chunk)
                    log.debug("[FB] uploaded %d/%d bytes", offset, file_size)
                except Exception as e:
                    log.error("[FB] chunk error at offset %d: %s", offset, e)
                    return False

        log.debug("[FB] file transfer complete: %d bytes uploaded", offset)
        return True

    def _finalize(self, video_id: str, caption: str,
                  thumbnail_path: Optional[Path] = None) -> Optional[str]:
        """Finalize upload and publish as Reel."""
        if not video_id:
            log.error("[FB] cannot finalize: video_id is empty/None")
            return None
            
        params = {
            "access_token": self.token,
            "upload_phase":  "finish",
            "video_id":      video_id,
            "description":   caption[:2200],
            "published":     "true" if self.published else "false",
        }
        if self.as_reel:
            params["video_state"] = "REELS_PUBLISHED" if self.published else "REELS_READY"

        url  = f"{GRAPH}/{self.page_id}/video_reels"
        data = urllib.parse.urlencode(params).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            post_id = result.get("post_id") or result.get("id")
            if not post_id:
                log.error("[FB] finalize response missing post_id/id: %s", result)
                return None
            return post_id
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            log.error("[FB] finalize HTTP error %d: %s", e.code, body)
            # Classify for retry engine
            if e.code in (401, 403):
                raise PermissionError(f"FB auth error {e.code}: {body}")
            if e.code == 429:
                raise RuntimeError(f"FB rate limit 429: {body}")
            raise RuntimeError(f"FB server error {e.code}: {body}")
        except Exception as e:
            log.error("[FB] finalize error: %s", e)
            return None

    def get_post_metrics(self, post_id: str) -> dict:
        """Pull engagement for a published post."""
        url = (f"{GRAPH}/{post_id}"
               f"?fields=likes.summary(true),comments.summary(true),shares"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            return {
                "likes":    data.get("likes",    {}).get("summary", {}).get("total_count", 0),
                "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares":   data.get("shares",   {}).get("count", 0),
            }
        except Exception as e:
            log.debug("[FB] metrics fetch failed %s: %s", post_id, e)
            return {}
