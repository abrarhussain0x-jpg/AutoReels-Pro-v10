"""
youtube_monitor.py — Real YouTube channel scraper using yt-dlp.
Finds new videos, filters by config rules, returns VideoMeta objects.
No API key needed. Uses yt-dlp + cookies for auth.
"""
from __future__ import annotations
import json, logging, subprocess, time, shutil, random, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

# Version/debug info
YT_DLP_MIN_VERSION = "2025.1.0"

@dataclass
class VideoMeta:
    video_id: str
    title: str
    url: str
    channel: str
    duration: int        # seconds
    view_count: int
    like_count: int
    upload_date: str     # YYYYMMDD
    description: str = ""
    tags: List[str] = field(default_factory=list)
    thumbnail_url: str = ""

class YouTubeMonitor:
    """Scrapes YouTube channels with yt-dlp. Zero cost, no API key."""

    def __init__(self, config: dict, cookies_file: str = "cloud/config/cookies.txt"):
        self.channels = config.get("channels", [])
        self.cookies  = cookies_file
        self.max_age  = 30   # days
        # Minimum delay between individual yt-dlp metadata calls (seconds)
        self.min_delay_between_calls = float(config.get("ytdlp_min_delay", 0.3))
        # Maximum metadata fetches per channel per run
        self.max_metadata_per_channel = int(config.get("max_metadata_per_channel", 20))
        # Detect a JavaScript runtime
        js_rt = None
        for candidate in ("node", "deno"):
            if shutil.which(candidate):
                js_rt = candidate
                log.info("[Monitor] Found JS runtime: %s", candidate)
                break
        self.js_runtime = js_rt
        # Rate-limit cooldown: epoch seconds until which calls should be skipped.
        self._cooldown_until = 0
        # Path to persist rate-limit cooldown across processes/runs
        self._cooldown_file = Path("cloud/queue/tmp/yt_dlp_rate_limit.json")
        # Verify yt-dlp is installed and working
        self._validate_ytdlp()

    def scan_all(self) -> List[VideoMeta]:
        """Scan all configured channels, return new candidates."""
        all_videos = []
        for ch in self.channels:
            # Respect persistent cooldown if set
            if self._is_rate_limited():
                log.warning("[Monitor] skipping channel scans due to yt-dlp rate-limit until %s", time.ctime(self._cooldown_until))
                break
            try:
                videos = self._scan_channel(ch)
                all_videos.extend(videos)
                log.info("[Monitor] %s → %d candidates", ch["url"], len(videos))
                # Gentle pause between channels to reduce request burst
                time.sleep(max(0.5, self.min_delay_between_calls / 2.0))
            except Exception as e:
                log.warning("[Monitor] channel scan failed %s: %s", ch.get("url"), e)
        return all_videos

    def _validate_ytdlp(self) -> None:
        """Validate that yt-dlp is installed and working."""
        try:
            r = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                version_str = r.stdout.strip()
                log.info("[Monitor] yt-dlp version: %s", version_str)
                return
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.error("[Monitor] CRITICAL: yt-dlp not available: %s", e)
            log.error("[Monitor] Install with: pip install -U yt-dlp")
            raise

    def _build_cmd_variants(self, base_cmd: list) -> list:
        """Build yt-dlp command variants with JS runtime and cookies."""
        if not base_cmd or not base_cmd[-1]:
            return [base_cmd]
        
        variants = []
        url = base_cmd[-1]
        base_without_url = base_cmd[:-1]
        
        # Variant 1: base command
        variants.append(base_cmd)
        
        # Variant 2: with JS runtime if available
        if self.js_runtime:
            cmd_with_js = base_without_url + ["--js-runtimes", self.js_runtime, url]
            variants.append(cmd_with_js)
        
        # Variant 3: with cookies if available
        if Path(self.cookies).exists():
            cmd_with_cookies = base_without_url + ["--cookies", self.cookies, url]
            variants.append(cmd_with_cookies)
            
            # Variant 4: with both JS runtime and cookies
            if self.js_runtime:
                cmd_with_both = base_without_url + ["--js-runtimes", self.js_runtime, "--cookies", self.cookies, url]
                variants.append(cmd_with_both)
        
        return variants

    def _scan_channel(self, ch: dict) -> List[VideoMeta]:
        url = ch["url"]
        # Aggressively scan: fetch up to 1000 videos per channel
        max_vids = ch.get("max_videos_per_run", 1000)
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--playlist-end", str(max_vids),
            "--no-warnings", "--extractor-args", "youtube:params={}",
        ]
        if self.js_runtime:
            cmd += ["--js-runtimes", self.js_runtime]
        if Path(self.cookies).exists():
            cmd += ["--cookies", self.cookies]
        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            start_ts = time.time()
            # Check stderr for explicit rate-limit message and set cooldown
            stderr = (result.stderr or "")
            if "rate-limited" in stderr.lower() or "The current session has been rate-limited" in stderr:
                # default: 1 hour cooldown
                self._set_rate_limit_cooldown(60 * 60)
                log.warning("[Monitor] detected yt-dlp rate-limit when scanning %s — entering cooldown", url)
            
            videos = []
            metadata_calls = 0
            # Collect non-empty lines from flat-playlist output
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            log.info("[Monitor] flat-playlist returned %d raw entries for %s", len(lines), url)
            
            # Limit number of metadata fetches per channel to avoid bursts
            lines = lines[: self.max_metadata_per_channel]
            for idx, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception as e:
                    log.warning(f"[Monitor] Failed to parse JSON at idx={idx}: {e}")
                    continue
                
                # Extract video ID or URL from flat-playlist entry
                vid_url = data.get("url") or data.get("id", "")
                if not vid_url:
                    log.debug(f"[Monitor] No video id/url at idx={idx}")
                    continue
                
                metadata_calls += 1
                meta = self._get_metadata(vid_url)
                if not meta:
                    log.info(f"[Monitor] Skipped video at idx={idx} id={vid_url}: no metadata returned (yt-dlp fail, rate-limit, or filtered)")
                    continue
                
                log.debug(f"[Monitor] Accepted video at idx={idx} id={vid_url}: {meta.title[:50]}")
                videos.append(meta)
                # Small jittered sleep between metadata calls to reduce rate-limit risk
                try:
                    s = self.min_delay_between_calls + random.random() * self.min_delay_between_calls
                    time.sleep(s)
                except Exception:
                    pass
            
            elapsed = time.time() - start_ts
            log.info("[Monitor] scanned %s: %d candidates, %d metadata calls, elapsed=%.1fs", url, len(videos), metadata_calls, elapsed)
            return videos
        except subprocess.TimeoutExpired:
            log.warning("[Monitor] yt-dlp timeout for %s", url)
            return []
        except FileNotFoundError:
            log.error("[Monitor] yt-dlp not installed. Run: pip install -U yt-dlp")
            return []

    def _get_metadata(self, video_url: str) -> Optional[VideoMeta]:
        if not video_url:
            log.debug("[Monitor] _get_metadata: empty URL")
            return None
        if self._is_rate_limited():
            log.info("[Monitor] skipping metadata fetch for %s due to yt-dlp cooldown", video_url)
            return None
        
        # Normalize video URL
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={video_url}"
        
        log.info("[Monitor] _get_metadata START for: %s", video_url[:80])
        
        # Try a sequence of yt-dlp invocations with fallbacks
        base_variants = [
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--no-check-certificate", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--allow-unplayable-formats", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--geo-bypass", video_url],
            ["yt-dlp", "--dump-json", "--no-warnings", "--skip-download", "--force-generic-extractor", video_url],
        ]
        
        # Build all variants with JS runtime + cookies combinations
        all_cmds = []
        for base_cmd in base_variants:
            all_cmds.extend(self._build_cmd_variants(base_cmd))
        
        log.info("[Monitor] _get_metadata: prepared %d command variants", len(all_cmds))
        
        attempt = 0
        for cmd in all_cmds:
            attempt += 1
            try:
                # Log at INFO level so we can see what's happening
                log.info("[Monitor] metadata attempt %d/%d for %s: %s", attempt, len(all_cmds), video_url, " ".join(cmd[:4] + ["..."]))
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                stderr = (r.stderr or "")
                
                # Detect yt-dlp rate-limit and persist cooldown
                if "rate-limited" in stderr.lower() or "The current session has been rate-limited" in stderr:
                    self._set_rate_limit_cooldown(60 * 60)
                    log.warning("[Monitor] detected yt-dlp rate-limit during metadata fetch %s — entering cooldown", video_url)
                    return None
                
                if r.returncode != 0 or not r.stdout:
                    log.info("[Monitor]   → attempt %d FAILED: code=%d, stdout_len=%d, stderr=(first 200 chars) %s", 
                             attempt, r.returncode, len(r.stdout or ""), stderr[:200])
                    # Save debug trace
                    if attempt == 1 or "rate-limit" in stderr.lower():
                        try:
                            debug_dir = Path("cloud/queue/tmp")
                            debug_dir.mkdir(parents=True, exist_ok=True)
                            vid = video_url.split("v=")[-1].split("&")[0][:20]
                            dbgfile = debug_dir / f"yt_dlp_debug_{vid}_{attempt}.log"
                            with dbgfile.open("w", encoding="utf-8") as fh:
                                fh.write(f"URL: {video_url}\n")
                                fh.write(f"Attempt: {attempt}/{len(all_cmds)}\n")
                                fh.write(f"CMD: {' '.join(cmd)}\n")
                                fh.write(f"CODE: {r.returncode}\n")
                                fh.write(f"STDERR (first 1000 chars):\n{stderr[:1000]}\n")
                        except Exception:
                            pass
                    
                    if "challenge solving failed" in stderr or "Only images are available" in stderr:
                        log.debug("[Monitor] JS challenge or images-only for %s at attempt %d", video_url, attempt)
                    continue
                
                # Success: parse JSON
                try:
                    data = json.loads(r.stdout.strip())
                    meta = VideoMeta(
                        video_id=data.get("id", ""),
                        title=data.get("title", ""),
                        url=data.get("webpage_url", video_url),
                        channel=data.get("channel", data.get("uploader", "")),
                        duration=int(data.get("duration", 0)),
                        view_count=int(data.get("view_count", 0)),
                        like_count=int(data.get("like_count", 0)),
                        upload_date=data.get("upload_date", ""),
                        description=(data.get("description", "") or "")[:500],
                        tags=data.get("tags", [])[:10],
                        thumbnail_url=data.get("thumbnail", ""),
                    )
                    log.info("[Monitor]   → attempt %d SUCCESS: got title='%s'", attempt, meta.title[:40])
                    return meta
                except Exception as e:
                    log.info("[Monitor]   → attempt %d JSON_PARSE_ERROR: %s", attempt, str(e)[:100])
                    continue
                    
            except subprocess.TimeoutExpired:
                log.info("[Monitor]   → attempt %d TIMEOUT (60s) for %s", attempt, video_url)
                continue
            except Exception as e:
                log.info("[Monitor]   → attempt %d ERROR: %s for %s", attempt, type(e).__name__, video_url)
                continue
        
        log.info("[Monitor] _get_metadata END FAILED: all %d metadata attempts failed for %s", len(all_cmds), video_url)
        return None

    def _set_rate_limit_cooldown(self, seconds: int = 3600) -> None:
        """Set an in-memory and persistent cooldown for yt-dlp calls."""
        try:
            until = int(time.time()) + int(seconds)
            self._cooldown_until = until
            # Ensure tmp dir exists
            self._cooldown_file.parent.mkdir(parents=True, exist_ok=True)
            with self._cooldown_file.open("w", encoding="utf-8") as fh:
                json.dump({"until": until}, fh)
        except Exception:
            # non-fatal: just set in-memory
            self._cooldown_until = int(time.time()) + int(seconds)

    def _is_rate_limited(self) -> bool:
        """Return True if a persistent or in-memory cooldown is active."""
        try:
            # Load persisted cooldown if present
            if self._cooldown_file.exists():
                try:
                    data = json.loads(self._cooldown_file.read_text(encoding="utf-8"))
                    self._cooldown_until = int(data.get("until", 0))
                except Exception:
                    pass
            return int(time.time()) < int(self._cooldown_until)
        except Exception:
            return False

    def _has_media_formats(self, video_url: str) -> bool:
        """Return True if yt-dlp reports at least one audio/video format for the URL."""
        try:
            base_variants = [
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--allow-unplayable-formats", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--no-check-certificate", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--force-generic-extractor", video_url],
            ]
            
            all_cmds = []
            for base_cmd in base_variants:
                all_cmds.extend(self._build_cmd_variants(base_cmd))
            
            for cmd in all_cmds:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    if r.returncode != 0 or not r.stdout:
                        continue
                    data = json.loads(r.stdout.strip())
                    formats = data.get("formats") or []
                    for f in formats:
                        vcodec = f.get("vcodec")
                        acodec = f.get("acodec")
                        if (vcodec and vcodec != "none") or (acodec and acodec != "none"):
                            return True
                except (subprocess.TimeoutExpired, Exception):
                    continue
            return False
        except Exception as e:
            log.debug("[Monitor] _has_media_formats error: %s", e)
            return False

    def download(self, video: VideoMeta, output_dir: Path,
                 quality: str = "bestvideo[height<=1080]+bestaudio/best") -> Optional[Path]:
        """Download a video. Returns path to downloaded file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_tpl = str(output_dir / f"{video.video_id}.%(ext)s")

        base_cmd = [
            "yt-dlp", "-f", quality,
            "--merge-output-format", "mp4",
            "-o", out_tpl, "--no-warnings",
            video.url
        ]
        
        # Build command variants with JS runtime and cookies
        cmds = self._build_cmd_variants(base_cmd)

        log.info("[Monitor] downloading %s: %s (trying %d variants)", video.video_id, video.title[:50], len(cmds))
        
        for attempt, cmd in enumerate(cmds, 1):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=600)
                if r.returncode == 0:
                    log.info("[Monitor] download SUCCESS for %s on attempt %d", video.video_id, attempt)
                    return output_dir / f"{video.video_id}.mp4"
                else:
                    err = r.stderr.decode() if isinstance(r.stderr, bytes) else str(r.stderr)
                    log.debug("[Monitor] download attempt %d failed for %s: %s", attempt, video.video_id, err[:200])
            except subprocess.TimeoutExpired:
                log.warning("[Monitor] download timeout for %s", video.video_id)
            except Exception as e:
                log.debug("[Monitor] download error for %s: %s", video.video_id, e)
        
        # Try fallback formats as last resort
        log.warning("[Monitor] initial download failed, trying fallback formats for %s", video.video_id)
        for fallback in ["bestvideo+bestaudio/best", "best"]:
            try:
                fb_cmd = ["yt-dlp", "-f", fallback, "--merge-output-format", "mp4",
                          "-o", out_tpl, "--no-warnings", video.url]
                r = subprocess.run(fb_cmd, capture_output=True, timeout=600)
                if r.returncode == 0:
                    log.info("[Monitor] download SUCCESS with fallback '%s' for %s", fallback, video.video_id)
                    return output_dir / f"{video.video_id}.mp4"
            except Exception as e:
                log.debug("[Monitor] fallback format '%s' failed: %s", fallback, e)
                continue
        
        log.error("[Monitor] all download attempts failed for %s", video.video_id)
        return None
