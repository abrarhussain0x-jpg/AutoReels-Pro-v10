"""
youtube_monitor.py — Real YouTube channel scraper using yt-dlp.
Finds new videos, filters by config rules, returns VideoMeta objects.
No API key needed. Uses yt-dlp + cookies for auth.
"""
from __future__ import annotations
import json, logging, subprocess, time
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

    def scan_all(self) -> List[VideoMeta]:
        """Scan all configured channels, return new candidates."""
        all_videos = []
        for ch in self.channels:
            try:
                videos = self._scan_channel(ch)
                all_videos.extend(videos)
                log.info("[Monitor] %s → %d candidates", ch["url"], len(videos))
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
        if Path(self.cookies).exists():
            cmd += ["--cookies", self.cookies]
        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            videos = []
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                # Always fetch full metadata for each video
                meta = self._get_metadata(data.get("url") or data.get("id", ""))
                if not meta:
                    continue
                # Do not filter by duration, keywords, or media formats
                videos.append(meta)
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
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={video_url}"
        # Try a sequence of yt-dlp invocations with fallbacks to handle
        # JS challenges, geo blocks, or unplayable formats. Return the
        # first successful metadata JSON parsed from stdout.
        cmds = [
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--no-check-certificate", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--allow-unplayable-formats", video_url],
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--geo-bypass", video_url],
            # Last-resort: force generic extractor or increase verbosity
            ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--skip-download", "--force-generic-extractor", video_url],
        ]
        if Path(self.cookies).exists():
            # ensure cookies arg is appended to each variant
            cmds = [c[:-1] + ["--cookies", self.cookies, c[-1]] for c in cmds]

        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                stderr = (r.stderr or "")
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

    def _has_media_formats(self, video_url: str) -> bool:
        """Return True if yt-dlp reports at least one audio/video format for the URL."""
        try:
            cmds = [
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--allow-unplayable-formats", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--no-check-certificate", video_url],
                ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", "--force-generic-extractor", video_url],
            ]
            if Path(self.cookies).exists():
                cmds = [c[:-1] + ["--cookies", self.cookies, c[-1]] for c in cmds]
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
