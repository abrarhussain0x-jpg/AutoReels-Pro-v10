"""
upload_dispatcher.py — Multi-platform upload dispatcher.
Single entry point that routes clips to FB, TikTok, Instagram, YouTube.
Handles per-platform rate limits, account rotation, and retry logic.
Returns a full UploadSummary with per-platform results.
"""
from __future__ import annotations
import logging, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class PlatformResult:
    platform:  str
    success:   bool
    post_id:   str = ""
    error:     str = ""
    duration_s: float = 0.0


@dataclass
class UploadSummary:
    video_id:   str
    clip_num:   int
    clip_path:  str
    caption:    str
    results:    List[PlatformResult] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def success_platforms(self) -> List[str]:
        return [r.platform for r in self.results if r.success]

    @property
    def failed_platforms(self) -> List[str]:
        return [r.platform for r in self.results if not r.success]


class UploadDispatcher:
    """Routes a clip to all configured + enabled platform uploaders."""

    def __init__(self, uploaders: dict, retry_engine=None, account_rotator=None):
        """
        uploaders: {"facebook": FacebookUploader, "tiktok": TikTokUploader, ...}
        """
        self.uploaders       = {k: v for k, v in uploaders.items()
                                if v is not None and v.is_configured()}
        self.retry_engine    = retry_engine
        self.account_rotator = account_rotator
        log.info("[Dispatcher] active platforms: %s", list(self.uploaders))

    def upload(
        self,
        clip_path: Path,
        caption: str,
        video_id: str,
        clip_num: int,
        thumbnail_path: Optional[Path] = None,
        gap_seconds: int = 45,
    ) -> UploadSummary:
        """Upload clip to all active platforms. Returns summary."""
        summary = UploadSummary(
            video_id=video_id,
            clip_num=clip_num,
            clip_path=str(clip_path),
            caption=caption,
        )

        for platform, uploader in self.uploaders.items():
            # Check account rotation
            if self.account_rotator:
                rotation = self.account_rotator.get_next_account(platform)
                if rotation.all_maxed:
                    log.info("[Dispatcher] %s all accounts maxed — skip", platform)
                    summary.results.append(PlatformResult(
                        platform=platform, success=False,
                        error="all accounts maxed for today",
                    ))
                    continue

            t0 = time.time()
            result = self._upload_one(platform, uploader, clip_path, caption, thumbnail_path)
            result.duration_s = time.time() - t0
            summary.results.append(result)

            # Record rotation
            if self.account_rotator and result.success:
                self.account_rotator.record_upload(platform, "default")
            elif self.account_rotator and not result.success:
                is_auth = "auth" in result.error.lower() or "401" in result.error
                self.account_rotator.record_failure(platform, "default", is_auth)

            # Gap between platforms
            if gap_seconds > 0 and list(self.uploaders)[-1] != platform:
                log.debug("[Dispatcher] gap %ds before next platform...", gap_seconds)
                time.sleep(gap_seconds)

        ok = sum(1 for r in summary.results if r.success)
        log.info("[Dispatcher] %s clip%d → %d/%d platforms OK",
                 video_id, clip_num, ok, len(self.uploaders))
        return summary

    def _upload_one(
        self,
        platform: str,
        uploader,
        clip_path: Path,
        caption: str,
        thumbnail_path: Optional[Path],
    ) -> PlatformResult:
        if self.retry_engine:
            res = self.retry_engine.call_with_retry(
                fn=lambda: uploader.upload(clip_path, caption, thumbnail_path),
                platform=platform,
                clip_path=str(clip_path),
                caption=caption,
            )
            if res.success:
                return PlatformResult(platform=platform, success=True,
                                      post_id=str(res.return_value or ""))
            return PlatformResult(platform=platform, success=False,
                                  error=res.error_message[:200])
        else:
            try:
                post_id = uploader.upload(clip_path, caption, thumbnail_path)
                if post_id:
                    return PlatformResult(platform=platform, success=True, post_id=str(post_id))
                return PlatformResult(platform=platform, success=False, error="no post_id returned")
            except Exception as e:
                return PlatformResult(platform=platform, success=False, error=str(e)[:200])
