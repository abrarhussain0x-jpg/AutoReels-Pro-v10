"""
video_processor.py — Real FFmpeg video processing pipeline.
Clips → resizes to 9:16 → burns hook text → adds watermark → exports.
All free. Only needs ffmpeg installed.
"""
from __future__ import annotations
import json, logging, os, subprocess, tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

@dataclass
class ClipJob:
    source_path: Path
    output_path: Path
    start_s: float
    duration_s: float
    clip_index: int
    hook_text: str = ""
    watermark_text: str = ""
    width: int = 1080
    height: int = 1920
    crf: int = 22
    preset: str = "fast"

@dataclass
class ProcessResult:
    clip_path: Path
    success: bool
    file_size_mb: float = 0.0
    error: str = ""

class VideoProcessor:
    """Full FFmpeg pipeline: cut → resize → overlay → encode."""

    def __init__(self, config: dict):
        out = config.get("output", {})
        self.width   = out.get("width", 1080)
        self.height  = out.get("height", 1920)
        self.crf     = out.get("crf", 22)
        self.preset  = out.get("preset", "fast")
        brand        = config.get("branding", {})
        self.channel = brand.get("channel_name", "")
        self.theme   = brand.get("theme", "classic")
        self.hw_accel = out.get("hardware_accel", False)
        # Determine a sensible font file for drawtext to avoid fontconfig issues
        # Prefer common system fonts on Linux and Windows; leave None if not found.
        self.fontfile = None
        try:
            # Linux common path
            linux_fp = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if linux_fp.exists():
                self.fontfile = str(linux_fp)
            else:
                # Windows common fonts
                win_candidates = [
                    Path("C:/Windows/Fonts/arialbd.ttf"),
                    Path("C:/Windows/Fonts/arial.ttf"),
                    Path("C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
                ]
                for p in win_candidates:
                    if p.exists():
                        self.fontfile = str(p)
                        break
        except Exception:
            self.fontfile = None

        self._check_ffmpeg()

    def _check_ffmpeg(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            log.info("[Processor] ffmpeg OK")
        except FileNotFoundError:
            log.error("[Processor] ffmpeg NOT FOUND. Install: sudo apt install ffmpeg")

    def process_clip(self, job: ClipJob) -> ProcessResult:
        """Cut + resize + overlay + encode a single clip."""
        job.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build video filter chain
        vf_parts = [
            # 1. Scale to fill 9:16 then crop center
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase",
            f"crop={self.width}:{self.height}",
        ]

        # 2. Hook text overlay (top of screen)
        if job.hook_text:
            safe_hook = job.hook_text.replace("'", "\\'").replace(":", "\\:")[:28]
            font_clause = f":fontfile={self.fontfile}" if self.fontfile else ""
            vf_parts.append(
                f"drawtext=text='{safe_hook}'"
                f":fontsize=72:fontcolor=yellow:bordercolor=black:borderw=3"
                f":x=(w-text_w)/2:y=80{font_clause}"
            )

        # 3. Part number (bottom left)
        part_text = f"PART {job.clip_index:02d}"
        font_clause = f":fontfile={self.fontfile}" if self.fontfile else ""
        vf_parts.append(
            f"drawtext=text='{part_text}'"
            f":fontsize=48:fontcolor=white:bordercolor=black:borderw=2"
            f":x=40:y=h-100{font_clause}"
        )

        # 4. Channel watermark (bottom right)
        if self.channel:
            safe_ch = self.channel.replace("'", "\\'")[:20]
            font_clause = f":fontfile={self.fontfile}" if self.fontfile else ""
            vf_parts.append(
                f"drawtext=text='{safe_ch}'"
                f":fontsize=36:fontcolor=white:alpha=0.7:bordercolor=black:borderw=1"
                f":x=w-text_w-40:y=h-80{font_clause}"
            )

        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(job.start_s),
            "-i", str(job.source_path),
            "-t", str(job.duration_s),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", self.preset,
            "-crf", str(self.crf),
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100",
            "-movflags", "+faststart",
            "-loglevel", "error",
            str(job.output_path),
        ]

        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0:
                err = (r.stderr.decode() if isinstance(r.stderr, (bytes, str)) else str(r.stderr))[:1000]
                # Detect fontconfig/font errors and retry without drawtext overlays
                if "Fontconfig error" in err or "Cannot load default config file" in err:
                    log.warning("[Processor] ffmpeg fontconfig error detected, retrying without drawtext overlays")
                    # Remove any drawtext filters
                    vf_nodraw = ",".join([p for p in vf_parts if not p.strip().startswith("drawtext=")])
                    # Build fallback command without -vf if empty
                    if vf_nodraw:
                        cmd_no_text = [
                            "ffmpeg", "-y",
                            "-ss", str(job.start_s),
                            "-i", str(job.source_path),
                            "-t", str(job.duration_s),
                            "-vf", vf_nodraw,
                            "-c:v", "libx264",
                            "-preset", self.preset,
                            "-crf", str(self.crf),
                            "-c:a", "aac", "-b:a", "128k",
                            "-ar", "44100",
                            "-movflags", "+faststart",
                            "-loglevel", "error",
                            str(job.output_path),
                        ]
                    else:
                        cmd_no_text = [
                            "ffmpeg", "-y",
                            "-ss", str(job.start_s),
                            "-i", str(job.source_path),
                            "-t", str(job.duration_s),
                            "-c:v", "libx264",
                            "-preset", self.preset,
                            "-crf", str(self.crf),
                            "-c:a", "aac", "-b:a", "128k",
                            "-ar", "44100",
                            "-movflags", "+faststart",
                            "-loglevel", "error",
                            str(job.output_path),
                        ]
                    try:
                        r2 = subprocess.run(cmd_no_text, capture_output=True, timeout=300)
                        if r2.returncode == 0:
                            size = job.output_path.stat().st_size / 1e6
                            log.info("[Processor] clip %d → %s (%.1f MB) [overlays skipped]", job.clip_index, job.output_path.name, size)
                            return ProcessResult(job.output_path, True, file_size_mb=size)
                        else:
                            err2 = (r2.stderr.decode() if isinstance(r2.stderr, (bytes, str)) else str(r2.stderr))[:300]
                            log.error("[Processor] ffmpeg retry without drawtext failed clip %d: %s", job.clip_index, err2)
                            return ProcessResult(job.output_path, False, error=err2)
                    except Exception as e:
                        return ProcessResult(job.output_path, False, error=str(e))
                # Other ffmpeg errors — report as before
                log.error("[Processor] ffmpeg error clip %d: %s", job.clip_index, err)
                return ProcessResult(job.output_path, False, error=err)

            size = job.output_path.stat().st_size / 1e6
            log.info("[Processor] clip %d → %s (%.1f MB)", job.clip_index, job.output_path.name, size)
            return ProcessResult(job.output_path, True, file_size_mb=size)

        except subprocess.TimeoutExpired:
            return ProcessResult(job.output_path, False, error="timeout")
        except Exception as e:
            return ProcessResult(job.output_path, False, error=str(e))

    def process_all_clips(
        self,
        source_path: Path,
        video_id: str,
        output_dir: Path,
        clips_config: List[dict],   # [{start_s, duration_s, hook_text}, ...]
    ) -> List[ProcessResult]:
        """Process all clips for a video. Returns list of results."""
        results = []
        for i, clip in enumerate(clips_config, 1):
            out_path = output_dir / f"{video_id}_clip{i:02d}.mp4"
            job = ClipJob(
                source_path=Path(source_path),
                output_path=out_path,
                start_s=clip["start_s"],
                duration_s=clip.get("duration_s", 55),
                clip_index=i,
                hook_text=clip.get("hook_text", ""),
                width=self.width,
                height=self.height,
                crf=self.crf,
                preset=self.preset,
            )
            result = self.process_clip(job)
            results.append(result)
        return results

    def extract_thumbnail(self, video_path: Path, time_s: float, output_path: Path) -> bool:
        """Extract a single frame as thumbnail."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-ss", str(time_s),
            "-i", str(video_path), "-frames:v", "1",
            "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height}",
            "-loglevel", "error", str(output_path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            return r.returncode == 0
        except Exception:
            return False

    def get_duration(self, video_path: Path) -> float:
        """Get video duration in seconds."""
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "json", str(video_path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return float(json.loads(r.stdout)["format"]["duration"])
        except Exception:
            return 0.0

    def smart_clip_times(self, duration: float, n_clips: int,
                         skip_start_pct: float = 0.08,
                         skip_end_pct: float = 0.05,
                         clip_length: int = 55) -> List[dict]:
        """Generate evenly-distributed clip start times, skipping intros/outros."""
        start_skip = duration * skip_start_pct
        end_skip   = duration * (1.0 - skip_end_pct)
        usable     = end_skip - start_skip
        step       = usable / max(1, n_clips)

        clips = []
        for i in range(n_clips):
            start = start_skip + i * step
            end   = min(start + clip_length, end_skip)
            if end - start < 20:
                continue
            clips.append({"start_s": round(start, 2), "duration_s": round(end - start, 2)})
        return clips
