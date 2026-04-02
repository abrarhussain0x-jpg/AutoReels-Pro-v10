"""
youtube_uploader.py — YouTube Shorts uploader via Data API v3.

Upload flow:
  1. Refresh OAuth2 access token from refresh_token
  2. Initialize resumable upload session (POST /upload/youtube/v3/videos)
  3. Stream video bytes in 10 MB chunks
  4. Confirm upload and return video_id

Requires:
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN in env
  Scopes: https://www.googleapis.com/auth/youtube.upload
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_BASE     = "https://www.googleapis.com/upload/youtube/v3/videos"
API_BASE        = "https://www.googleapis.com/youtube/v3"
CHUNK_SIZE      = 10 * 1024 * 1024   # 10 MB

# YouTube Shorts require portrait video <= 60s, but we still allow longer uploads.
# The platform decides Shorts eligibility; we tag with #Shorts in the title.
MAX_TITLE_LEN = 100
MAX_DESC_LEN  = 5000
MAX_TAGS      = 500  # total character limit across all tags


class YouTubeUploader:
    """Uploads video clips as YouTube Shorts via the Data API v3."""

    def __init__(
        self,
        client_id:     str,
        client_secret: str,
        refresh_token: str,
        privacy_status: str = "public",
        category_id:    str = "22",    # People & Blogs; 24 = Entertainment
        made_for_kids:  bool = False,
    ):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.privacy       = privacy_status
        self.category_id   = category_id
        self.made_for_kids = made_for_kids
        self._access_token: str = ""
        self._token_expiry: float = 0.0

    # ── Public API ──────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(
            self.client_id and self.client_secret and self.refresh_token
            and not self.client_id.startswith("${")
            and not self.refresh_token.startswith("${")
        )

    def upload(
        self,
        clip_path: Path,
        caption: str,
        thumbnail_path: Optional[Path] = None,
    ) -> Optional[str]:
        """
        Upload a video clip as a YouTube Short.

        Returns video_id (e.g. ``dQw4w9WgXcQ``) on success, None on failure.
        """
        clip_path = Path(clip_path)
        if not clip_path.exists():
            log.error("[YT] clip not found: %s", clip_path)
            return None

        token = self._get_access_token()
        if not token:
            log.error("[YT] could not obtain access token")
            return None

        file_size = clip_path.stat().st_size
        log.info("[YT] uploading %s (%.1f MB)", clip_path.name, file_size / 1e6)

        # Build metadata — append #Shorts so YouTube indexes it correctly
        title, description, tags = self._build_metadata(caption)

        # Step 1: initialise resumable upload session
        upload_url = self._init_resumable_upload(token, file_size, title, description, tags)
        if not upload_url:
            return None

        # Step 2: stream the file
        video_id = self._upload_file(upload_url, clip_path, file_size, token)
        if not video_id:
            return None

        # Step 3: optionally set thumbnail
        if thumbnail_path and Path(thumbnail_path).exists():
            self._set_thumbnail(video_id, Path(thumbnail_path), token)

        log.info("[YT] ✅ uploaded → video_id=%s", video_id)
        return video_id

    def get_video_metrics(self, video_id: str) -> dict:
        """Pull view/like/comment counts for a published video."""
        token = self._get_access_token()
        if not token:
            return {}
        url = (
            f"{API_BASE}/videos"
            f"?part=statistics&id={video_id}"
        )
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            items = data.get("items", [])
            if not items:
                return {}
            stats = items[0].get("statistics", {})
            return {
                "views":    int(stats.get("viewCount",    0)),
                "likes":    int(stats.get("likeCount",    0)),
                "comments": int(stats.get("commentCount", 0)),
            }
        except Exception as e:
            log.debug("[YT] metrics fetch failed %s: %s", video_id, e)
            return {}

    # ── OAuth2 ──────────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        body = urllib.parse.urlencode({
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type":    "refresh_token",
        }).encode()

        try:
            req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            self._access_token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 3600))
            self._token_expiry = time.time() + expires_in
            log.debug("[YT] access token refreshed (expires in %ds)", expires_in)
            return self._access_token
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode()[:300]
            log.error("[YT] token refresh failed %d: %s", e.code, body_txt)
            if e.code in (400, 401):
                raise PermissionError(f"YT OAuth error {e.code}: invalid credentials")
            return ""
        except Exception as e:
            log.error("[YT] token refresh error: %s", e)
            return ""

    # ── Upload steps ─────────────────────────────────────────────────────────

    def _init_resumable_upload(
        self,
        token: str,
        file_size: int,
        title: str,
        description: str,
        tags: list,
    ) -> Optional[str]:
        """POST to initiate resumable upload; returns the upload URI."""
        metadata = {
            "snippet": {
                "title":       title[:MAX_TITLE_LEN],
                "description": description[:MAX_DESC_LEN],
                "tags":        tags,
                "categoryId":  self.category_id,
            },
            "status": {
                "privacyStatus":      self.privacy,
                "selfDeclaredMadeForKids": self.made_for_kids,
            },
        }
        body = json.dumps(metadata).encode()
        url  = f"{UPLOAD_BASE}?uploadType=resumable&part=snippet,status"

        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization",  f"Bearer {token}")
        req.add_header("Content-Type",   "application/json; charset=UTF-8")
        req.add_header("X-Upload-Content-Type",   "video/mp4")
        req.add_header("X-Upload-Content-Length", str(file_size))

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                upload_url = resp.getheader("Location", "")
            if not upload_url:
                log.error("[YT] no Location header in resumable init response")
                return None
            log.debug("[YT] resumable upload URL obtained")
            return upload_url
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode()[:300]
            log.error("[YT] init upload error %d: %s", e.code, body_txt)
            if e.code in (401, 403):
                raise PermissionError(f"YT auth error {e.code}")
            if e.code == 429:
                raise RuntimeError("YT quota exceeded (429)")
            return None
        except Exception as e:
            log.error("[YT] init upload exception: %s", e)
            return None

    def _upload_file(
        self,
        upload_url: str,
        clip_path: Path,
        file_size: int,
        token: str,
    ) -> Optional[str]:
        """Stream file bytes to upload_url. Returns video_id on completion."""
        offset = 0
        total_chunks = math.ceil(file_size / CHUNK_SIZE)

        with open(clip_path, "rb") as fh:
            chunk_num = 0
            while offset < file_size:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                content_range = f"bytes {offset}-{end}/{file_size}"

                req = urllib.request.Request(upload_url, data=chunk, method="PUT")
                req.add_header("Authorization",  f"Bearer {token}")
                req.add_header("Content-Length", str(len(chunk)))
                req.add_header("Content-Type",   "video/mp4")
                req.add_header("Content-Range",  content_range)

                try:
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        status = resp.status
                        if status in (200, 201):
                            data = json.loads(resp.read())
                            return data.get("id")
                        # 308 Resume Incomplete — continue uploading
                        offset += len(chunk)
                except urllib.error.HTTPError as e:
                    if e.code == 308:
                        # Resume incomplete — normal for chunked uploads
                        range_header = e.headers.get("Range", "")
                        if range_header:
                            offset = int(range_header.split("-")[-1]) + 1
                        else:
                            offset += len(chunk)
                    elif e.code in (500, 502, 503):
                        log.warning("[YT] server error %d on chunk %d — retrying", e.code, chunk_num)
                        time.sleep(2 ** min(chunk_num, 4))
                    else:
                        log.error("[YT] upload error %d on chunk %d", e.code, chunk_num)
                        return None
                except Exception as e:
                    log.error("[YT] chunk error at offset %d: %s", offset, e)
                    return None

                chunk_num += 1
                log.debug("[YT] chunk %d/%d uploaded (%d/%d bytes)",
                          chunk_num, total_chunks, offset, file_size)

        log.error("[YT] upload loop ended without 200/201 — no video_id returned")
        return None

    def _set_thumbnail(self, video_id: str, thumbnail_path: Path, token: str) -> bool:
        """Upload a custom thumbnail for the video."""
        url = f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}"

        with open(thumbnail_path, "rb") as fh:
            thumb_bytes = fh.read()

        ext = thumbnail_path.suffix.lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        req = urllib.request.Request(url, data=thumb_bytes, method="POST")
        req.add_header("Authorization",  f"Bearer {token}")
        req.add_header("Content-Type",   mime)
        req.add_header("Content-Length", str(len(thumb_bytes)))
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
            log.debug("[YT] thumbnail set for %s", video_id)
            return True
        except Exception as e:
            log.warning("[YT] thumbnail upload failed: %s", e)
            return False

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_metadata(caption: str) -> tuple[str, str, list]:
        """
        Split caption into title / description / tags.
        Injects #Shorts for YouTube Shorts indexing.
        """
        lines = [l.strip() for l in caption.split("\n") if l.strip()]
        title = (lines[0] if lines else "Watch This")[:MAX_TITLE_LEN]
        # Ensure #Shorts appears in title for Shorts indexing
        if "#shorts" not in title.lower():
            # Append if there's room, otherwise shorten
            shorts_tag = " #Shorts"
            if len(title) + len(shorts_tag) <= MAX_TITLE_LEN:
                title += shorts_tag
            else:
                title = title[:MAX_TITLE_LEN - len(shorts_tag)] + shorts_tag

        description = "\n".join(lines[1:])[:MAX_DESC_LEN] if len(lines) > 1 else caption[:MAX_DESC_LEN]

        # Extract hashtags from caption
        import re
        raw_tags = re.findall(r"#(\w+)", caption)
        tags     = list(dict.fromkeys(raw_tags))   # deduplicate, preserve order
        # Enforce total character limit
        selected, total = [], 0
        for tag in tags:
            if total + len(tag) + 1 > MAX_TAGS:
                break
            selected.append(tag)
            total += len(tag) + 1

        return title, description, selected

    @classmethod
    def from_env(cls) -> "YouTubeUploader":
        """Construct from environment variables."""
        return cls(
            client_id     = os.getenv("YOUTUBE_CLIENT_ID",     ""),
            client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", ""),
            refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", ""),
            privacy_status= os.getenv("YOUTUBE_PRIVACY",       "public"),
            category_id   = os.getenv("YOUTUBE_CATEGORY_ID",   "22"),
        )
