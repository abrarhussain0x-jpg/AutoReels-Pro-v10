"""
video_enhancer.py — Free video enhancement pipeline using FFmpeg only.
Applies: color grading, subtle Ken Burns zoom, audio normalization,
and fade in/out transitions. Makes clips look more professional.
Zero cost. No external ML models needed.
"""
from __future__ import annotations
import logging, subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Color grade presets (FFmpeg eq + curves filters)
COLOR_GRADES = {
    "cinematic": "eq=contrast=1.15:brightness=-0.02:saturation=0.85,curves=r='0/0 0.5/0.45 1/1':g='0/0 0.5/0.5 1/0.95':b='0/0.05 0.5/0.52 1/1'",
    "warm":      "eq=contrast=1.1:brightness=0.02:saturation=1.1,colorchannelmixer=rr=1.05:gg=1.0:bb=0.9",
    "cool":      "eq=contrast=1.1:brightness=-0.01:saturation=0.9,colorchannelmixer=rr=0.95:gg=1.0:bb=1.1",
    "vivid":     "eq=contrast=1.2:brightness=0.0:saturation=1.3",
    "dark":      "eq=contrast=1.3:brightness=-0.05:saturation=0.8,vignette=PI/4",
    "none":      "",
}


class VideoEnhancer:
    """Applies professional video enhancements using FFmpeg filters."""

    def __init__(
        self,
        color_grade:    bool  = True,
        ken_burns:      bool  = True,
        audio_normalize:bool  = True,
        fade_duration:  float = 0.3,
        grade_preset:   str   = "cinematic",
    ):
        self.color_grade     = color_grade
        self.ken_burns       = ken_burns
        self.audio_normalize = audio_normalize
        self.fade_duration   = fade_duration
        self.grade_preset    = grade_preset
        log.info("[Enhancer] grade=%s kb=%s audio=%s",
                 grade_preset if color_grade else "off",
                 ken_burns, audio_normalize)

    def enhance(self, input_path: Path, output_path: Path,
                width: int = 1080, height: int = 1920) -> bool:
        """Apply all enabled enhancements to a clip. Returns True on success."""
        input_path  = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        vf_parts = []
        af_parts = []

        # ── Ken Burns zoom (subtle 1.0→1.05 zoom over clip duration) ─────────
        if self.ken_burns:
            vf_parts.append(
                f"scale={width*2}:{height*2},"
                f"zoompan=z='min(zoom+0.0005,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={width}x{height}:fps=30"
            )
        else:
            vf_parts.append(f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}")

        # ── Color grade ────────────────────────────────────────────────────────
        if self.color_grade:
            grade = COLOR_GRADES.get(self.grade_preset, COLOR_GRADES["cinematic"])
            if grade:
                vf_parts.append(grade)

        # ── Fade in/out ────────────────────────────────────────────────────────
        fd = self.fade_duration
        vf_parts.append(f"fade=t=in:st=0:d={fd}")
        vf_parts.append(f"fade=t=out:st=-{fd}:d={fd}")

        # ── Audio normalization (loudnorm) ─────────────────────────────────────
        if self.audio_normalize:
            af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        af_parts.append(f"afade=t=in:ss=0:d={fd}")
        af_parts.append(f"afade=t=out:st=-{fd}:d={fd}")

        vf = ",".join(vf_parts)
        af = ",".join(af_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-loglevel", "error",
            str(output_path),
        ]

        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0:
                log.error("[Enhancer] ffmpeg error: %s", r.stderr.decode()[:200])
                return False
            size_mb = output_path.stat().st_size / 1e6
            log.info("[Enhancer] ✅ enhanced → %s (%.1f MB)", output_path.name, size_mb)
            return True
        except subprocess.TimeoutExpired:
            log.error("[Enhancer] timeout on %s", input_path.name)
            return False
        except Exception as e:
            log.error("[Enhancer] error: %s", e)
            return False

    def normalize_audio_only(self, input_path: Path, output_path: Path) -> bool:
        """Quick audio-only normalization pass (faster than full enhance)."""
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-loglevel", "error", str(output_path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            return r.returncode == 0
        except Exception as e:
            log.error("[Enhancer] audio norm error: %s", e)
            return False
