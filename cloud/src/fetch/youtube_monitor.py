"""
youtube_monitor.py — Real YouTube channel scraper using yt-dlp.
Finds new videos, filters by config rules, returns VideoMeta objects.
No API key needed. Uses yt-dlp + cookies for auth.
"""
from __future__ import annotations
import json, logging, subprocess, time, shutil, random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

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
        # Lower default to speed up runs; can be overridden via config key `ytdlp_min_delay`.
        self.min_delay_between_calls = float(config.get("ytdlp_min_delay", 0.5))
        # Maximum metadata fetches per channel per run (conservative default)
        # Reduce default to limit run time; override with `max_metadata_per_channel` in config.
        self.max_metadata_per_channel = int(config.get("max_metadata_per_channel", 12))
        # Detect a JavaScript runtime (yt-dlp can use node or deno for JS).
        # Only pass the --js-runtimes flag when a runtime is available.
        js_rt = None
        for candidate in ("node", "deno"):
            if shutil.which(candidate):
                js_rt = candidate
                break
        self.js_runtime = js_rt
        # Rate-limit cooldown: epoch seconds until which calls should be skipped.
        self._cooldown_until = 0
        # Path to persist rate-limit cooldown across processes/runs
        self._cooldown_file = Path("cloud/queue/tmp/yt_dlp_rate_limit.json")

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

    def _scan_channel(self, ch: dict) -> List[VideoMeta]:
        url = ch["url"]
        # Aggressively scan: fetch up to 1000 videos per channel
        max_vids = ch.get("max_videos_per_run", 1000)
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--playlist-end", str(max_vids),
            "--no-warnings",
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
            if "rate-limited" in stderr or "rate limited" in stderr or "The current session has been rate-limited" in stderr:
                # default: 1 hour cooldown
                self._set_rate_limit_cooldown(60 * 60)
                log.warning("[Monitor] detected yt-dlp rate-limit when scanning %s — entering cooldown", url)
            videos = []
            metadata_calls = 0
            # Collect non-empty lines from flat-playlist output
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            # Limit number of metadata fetches per channel to avoid bursts
            lines = lines[: self.max_metadata_per_channel]
            for idx, line in enumerate(lines):
                if not line.strip():
                    log.debug(f"[Monitor] Skipping empty line at idx={idx}")
                    continue
                try:
                    data = json.loads(line)
                except Exception as e:
                    log.warning(f"[Monitor] Failed to parse JSON at idx={idx}: {e} line={line[:120]}")
                    continue
                vid_id = data.get("url") or data.get("id", "")
                if not vid_id:
                    log.warning(f"[Monitor] No video id/url at idx={idx}: {data}")
                    continue
                meta = self._get_metadata(vid_id)
                if not meta:
                    log.info(f"[Monitor] Skipped video at idx={idx} id={vid_id}: no metadata returned (yt-dlp fail, rate-limit, or filtered)")
                    continue
                # Do not filter by duration, keywords, or media formats
                log.debug(f"[Monitor] Accepted video at idx={idx} id={vid_id}: {meta.title}")
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
            log.error("[Monitor] yt-dlp not installed. Run: pip install yt-dlp")
            return []

    def _get_metadata(self, video_url: str) -> Optional[VideoMeta]:
        if not video_url:
            return None
        if self._is_rate_limited():
            log.debug("[Monitor] skipping metadata fetch for %s due to yt-dlp cooldown", video_url)
            return None
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={video_url}"
        # Try a sequence of yt-dlp invocations with fallbacks to handle
        # JS challenges, geo blocks, or unplayable formats. Return the
        # first successful metadata JSON parsed from stdout.
        base_variants = [
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--no-check-certificate", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--allow-unplayable-formats", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--geo-bypass", video_url],
            # Last-resort: force generic extractor or increase verbosity
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--force-generic-extractor", video_url],
        ]
        cmds = []
        # Build variants; include both with and without cookies (if available)
        for v in base_variants:
            variants = []
            if self.js_runtime:
                variants.append(v[:-1] + ["--js-runtimes", self.js_runtime, v[-1]])
            else:
                variants.append(v)
            # If cookies file exists, also try the same variant with cookies
            if Path(self.cookies).exists():
                for base in list(variants):
                    variants.append(base[:-1] + ["--cookies", self.cookies, base[-1]])
            # extend main cmds list
            cmds.extend(variants)

        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                stderr = (r.stderr or "")
                # Detect yt-dlp rate-limit and persist cooldown
                if "rate-limited" in stderr or "rate limited" in stderr or "The current session has been rate-limited" in stderr:
                    self._set_rate_limit_cooldown(60 * 60)
                    log.warning("[Monitor] detected yt-dlp rate-limit during metadata fetch %s — entering cooldown", video_url)
                if r.returncode != 0 or not r.stdout:
                    # Persist a short debug trace for post-mortem in cloud/queue/tmp
                    try:
                        debug_dir = Path("cloud/queue/tmp")
                        debug_dir.mkdir(parents=True, exist_ok=True)
                        vid = video_url.split("v=")[-1].split("&")[0]
                        dbgfile = debug_dir / f"yt_dlp_debug_{vid}.log"
                        with dbgfile.open("a", encoding="utf-8") as fh:
                            fh.write(f"CMD: {' '.join(cmd)}\n")
                            fh.write((r.stderr or "")[:800] + "\n\n")
                    except Exception:
                        pass
                    if "challenge solving failed" in stderr or "Only images are available" in stderr:
                        log.warning("[Monitor] yt-dlp JS challenge or images-only for %s — stderr=%s", video_url, stderr[:200])
                    else:
                        log.debug("[Monitor] metadata attempt non-zero exit for %s: cmd=%s stderr=%s", video_url, cmd, stderr[:200])
                    continue
                data = json.loads(r.stdout.strip())
                return VideoMeta(
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
            except subprocess.TimeoutExpired:
                log.warning("[Monitor] yt-dlp metadata timeout for %s (cmd=%s)", video_url, cmd)
                continue
            except Exception as e:
                log.debug("[Monitor] metadata failed %s: %s", video_url, e)
                continue
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
            cmds = []
            for v in base_variants:
                if self.js_runtime:
                    cmds.append(v[:-1] + ["--js-runtimes", self.js_runtime, v[-1]])
                else:
                    cmds.append(v)
            # Also try variants with and without cookies
            expanded = []
            for v in base_variants:
                if self.js_runtime:
                    expanded.append(v[:-1] + ["--js-runtimes", self.js_runtime, v[-1]])
                else:
                    expanded.append(v)
                if Path(self.cookies).exists():
                    # add cookie-enabled variant
                    expanded.append((v[:-1] + ["--cookies", self.cookies, v[-1]]) if not self.js_runtime else v[:-1] + ["--js-runtimes", self.js_runtime, v[-1], "--cookies", self.cookies])
            cmds = expanded
            for cmd in cmds:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    stderr = (r.stderr or "")
                    if r.returncode != 0 or not r.stdout:
                        # Save debug traces for investigation
                        try:
                            debug_dir = Path("cloud/queue/tmp")
                            debug_dir.mkdir(parents=True, exist_ok=True)
                            vid = video_url.split("v=")[-1].split("&")[0]
                            dbgfile = debug_dir / f"yt_dlp_formats_{vid}.log"
                            with dbgfile.open("a", encoding="utf-8") as fh:
                                fh.write(f"CMD: {' '.join(cmd)}\n")
                                fh.write((r.stderr or "")[:800] + "\n\n")
                        except Exception:
                            pass
                        log.debug("[Monitor] formats attempt non-zero for %s cmd=%s stderr=%s", video_url, cmd, stderr[:200])
                        continue
                    data = json.loads(r.stdout.strip())
                    formats = data.get("formats") or []
                    for f in formats:
                        vcodec = f.get("vcodec")
                        acodec = f.get("acodec")
                        if (vcodec and vcodec != "none") or (acodec and acodec != "none"):
                            return True
                except subprocess.TimeoutExpired:
                    log.warning("[Monitor] yt-dlp formats timeout for %s (cmd=%s)", video_url, cmd)
                    continue
                except Exception as e:
                    log.debug("[Monitor] _has_media_formats error %s: %s", video_url, e)
                    continue
            return False
        except Exception as e:
            log.debug("[Monitor] _has_media_formats error %s: %s", video_url, e)
            return False

    def download(self, video: VideoMeta, output_dir: Path,
                 quality: str = "bestvideo[height<=1080]+bestaudio/best") -> Optional[Path]:
        """Download a video. Returns path to downloaded file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_tpl = str(output_dir / f"{video.video_id}.%(ext)s")

        cmd = [
            "yt-dlp", "-f", quality,
            "--merge-output-format", "mp4",
            "-o", out_tpl, "--no-warnings",
        ]
        if self.js_runtime:
            cmd += ["--js-runtimes", self.js_runtime]
        if Path(self.cookies).exists():
            cmd += ["--cookies", self.cookies]
        cmd.append(video.url)

        log.info("[Monitor] downloading %s: %s", video.video_id, video.title[:50])
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode != 0:
                err = r.stderr.decode() if isinstance(r.stderr, (bytes, str)) else str(r.stderr)
                log.warning("[Monitor] initial download failed, trying fallback formats: %s", err[:200])
                # Try fallback formats
                for fallback in ["bestvideo+bestaudio/best", "best"]:
                    try:
                        fb_cmd = ["yt-dlp", "-f", fallback, "--merge-output-format", "mp4",
                                  "-o", out_tpl, "--no-warnings"]
                        if self.js_runtime:
                            fb_cmd += ["--js-runtimes", self.js_runtime]
                        if Path(self.cookies).exists():
                            fb_cmd += ["--cookies", self.cookies]
                        fb_cmd.append(video.url)
                        r2 = subprocess.run(fb_cmd, capture_output=True, timeout=600)
                        if r2.returncode == 0:
                            r = r2
                            break
                    except Exception:
                        continue
                else:
                    log.error("[Monitor] download failed: %s", err[:200])
                    return None
            # Find output file
            for f in output_dir.glob(f"{video.video_id}.*"):
                if f.suffix in (".mp4", ".mkv", ".webm"):
                    log.info("[Monitor] downloaded → %s (%.1f MB)",
                             f.name, f.stat().st_size / 1e6)
                    return f
        except subprocess.TimeoutExpired:
            log.error("[Monitor] download timeout for %s", video.video_id)
        except FileNotFoundError:
            log.error("[Monitor] yt-dlp not installed")
        return None
