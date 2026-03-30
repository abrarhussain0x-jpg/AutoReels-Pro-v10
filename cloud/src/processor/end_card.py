"""
end_card.py — Burns end card overlay into last 3 seconds of every clip.

The end card tells viewers exactly what to do next:
  - Follow the page
  - Watch Part N
  - What to expect

Facebook gives massive weight to watch-to-end completion rate.
An end card ensures viewers know to follow BEFORE they leave.
Works with FFmpeg drawtext. Zero cost.
"""
from __future__ import annotations
import logging, subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

END_CARD_STYLES = {
    "minimal": {
        "bg_color":   "black@0.6",
        "text_color": "white",
        "accent":     "yellow",
    },
    "bold": {
        "bg_color":   "red@0.8",
        "text_color": "white",
        "accent":     "yellow",
    },
    "clean": {
        "bg_color":   "black@0.75",
        "text_color": "white",
        "accent":     "00d4ff",
    },
}


class EndCardBurner:
    """Burns animated end card into final seconds of clip using FFmpeg."""

    def __init__(self, style: str = "minimal", duration: float = 2.5):
        self.style    = END_CARD_STYLES.get(style, END_CARD_STYLES["minimal"])
        self.duration = duration  # seconds of end card

    def burn(
        self,
        input_path: Path,
        output_path: Path,
        channel_name: str,
        next_part: int,
        clip_index: int,
    ) -> bool:
        """Add end card overlay to a clip. Returns True on success."""
        input_path  = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get clip duration
        dur = self._get_duration(input_path)
        if dur < 5:
            log.warning("[EndCard] clip too short (%.1fs) — skip", dur)
            return self._copy(input_path, output_path)

        end_start = max(0, dur - self.duration)
        safe_ch   = channel_name.replace("'", "\\'")[:20]
        text1     = f"FOLLOW @{safe_ch}"
        text2     = f"PART {next_part} NEXT \u25ba"

        # Build FFmpeg drawtext filters
        # Background rectangle for end card
        end_card_vf = (
            # Darken bottom section for end card
            f"drawbox=y=ih*0.70:w=iw:h=ih*0.30:color=black@0.75:t=fill"
            f":enable='gte(t,{end_start})',"
            # Main CTA text (follow)
            f"drawtext=text='{text1}'"
            f":fontsize=62:fontcolor=yellow:bordercolor=black:borderw=3"
            f":x=(w-text_w)/2:y=h*0.74"
            f":enable='gte(t,{end_start})',"
            # Sub text (next part)
            f"drawtext=text='{text2}'"
            f":fontsize=48:fontcolor=white:bordercolor=black:borderw=2"
            f":x=(w-text_w)/2:y=h*0.84"
            f":enable='gte(t,{end_start})'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", end_card_vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            "-loglevel", "error",
            str(output_path),
        ]

        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0:
                log.error("[EndCard] ffmpeg error: %s", r.stderr.decode()[:200])
                return self._copy(input_path, output_path)
            log.info("[EndCard] burned end card → %s", output_path.name)
            return True
        except Exception as e:
            log.error("[EndCard] error: %s", e)
            return self._copy(input_path, output_path)

    def _get_duration(self, path: Path) -> float:
        import json
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "json", str(path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(json.loads(r.stdout)["format"]["duration"])
        except Exception:
            return 0.0

    def _copy(self, src: Path, dst: Path) -> bool:
        import shutil
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False
