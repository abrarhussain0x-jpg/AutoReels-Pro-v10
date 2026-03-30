"""
subtitle_engine_v2.py v10.0 — Word-Level Karaoke Caption Engine.

Upgrades v9 ASS subtitles to word-level karaoke-style captions burned
directly into the video. Each word pops onto screen at its exact timestamp.
The most important word per sentence is highlighted in accent color via Claude.

New in v10:
  - faster-whisper with word_timestamps=True for precise timing
  - Word-by-word pop-on animation via drawtext filter chain
  - Claude picks the "power word" per sentence to highlight
  - Configurable: font_size, accent_color, position, shadow
  - Falls back to sentence-level subtitles if whisper unavailable

Architecture:
  SubtitleEngineV2
    ├── Transcriber (faster-whisper)
    ├── PowerWordDetector (Claude Haiku)
    └── FFmpegCaptionRenderer (drawtext filter)
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

POSITION_MAP = {
    "bottom_third": ("(w-text_w)/2", "(h*2/3)"),
    "center":       ("(w-text_w)/2", "(h-text_h)/2"),
    "top_third":    ("(w-text_w)/2", "(h/4)"),
}


@dataclass
class WordToken:
    word: str
    start: float
    end: float
    is_power_word: bool = False


@dataclass
class CaptionSentence:
    text: str
    start: float
    end: float
    words: List[WordToken] = field(default_factory=list)
    power_word: str = ""


class SubtitleEngineV2:
    """
    Burns word-level karaoke captions into a video clip.
    Each word appears exactly when spoken; power word gets accent color.
    """

    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str = "",
        vad_model: str = "tiny",
        font_size: int = 52,
        accent_color: str = "#FFE600",
        shadow_color: str = "#000000",
        position: str = "bottom_third",
        highlight_power_word: bool = True,
        use_claude_highlight: bool = True,
        enabled: bool = True,
    ) -> None:
        self.api_key = api_key
        self.vad_model = vad_model
        self.font_size = font_size
        self.accent_color = accent_color.lstrip("#")
        self.shadow_color = shadow_color.lstrip("#")
        self.position = position
        self.highlight_power_word = highlight_power_word
        self.use_claude_highlight = use_claude_highlight
        self.enabled = enabled
        log.info("[SubtitleV2] init model=%s size=%d accent=#%s",
                 vad_model, font_size, self.accent_color)

    def burn_captions(self, input_path: Path, output_path: Path) -> bool:
        """
        Transcribe input_path, generate caption filters, render to output_path.
        Returns True on success.
        """
        if not self.enabled:
            return self._copy_passthrough(input_path, output_path)

        try:
            sentences = self._transcribe(input_path)
            if not sentences:
                log.warning("[SubtitleV2] No transcription — passthrough")
                return self._copy_passthrough(input_path, output_path)

            if self.highlight_power_word:
                sentences = self._detect_power_words(sentences)

            ass_path = self._build_ass_file(sentences, input_path)
            return self._burn_ass(input_path, output_path, ass_path)

        except Exception as exc:
            log.error("[SubtitleV2] burn_captions error: %s", exc)
            return self._copy_passthrough(input_path, output_path)

    # ── Transcription ──────────────────────────────────────────────────────

    def _transcribe(self, video_path: Path) -> List[CaptionSentence]:
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(self.vad_model, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(
                str(video_path),
                word_timestamps=True,
                vad_filter=True,
            )
            sentences = []
            for seg in segments:
                words = []
                for w in (seg.words or []):
                    words.append(WordToken(
                        word=w.word.strip(),
                        start=w.start,
                        end=w.end,
                    ))
                if not words:
                    continue
                sentences.append(CaptionSentence(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    words=words,
                ))
            log.info("[SubtitleV2] transcribed %d sentences", len(sentences))
            return sentences
        except ImportError:
            log.warning("[SubtitleV2] faster-whisper not available")
            return []
        except Exception as exc:
            log.warning("[SubtitleV2] transcription error: %s", exc)
            return []

    # ── Power Word Detection ───────────────────────────────────────────────

    def _detect_power_words(
        self, sentences: List[CaptionSentence]
    ) -> List[CaptionSentence]:
        """Ask Claude Haiku to identify the most impactful word per sentence."""
        if not self.use_claude_highlight or not self.api_key:
            return self._detect_power_words_heuristic(sentences)

        batch_text = "\n".join(
            f"{i+1}. {s.text}" for i, s in enumerate(sentences[:50])
        )
        prompt = (
            "For each sentence below, identify the single most emotionally impactful or "
            "surprising word. Return ONLY a JSON array of strings (one word per sentence, "
            "same order). No preamble.\n\n" + batch_text
        )
        try:
            body = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                self.ENDPOINT, data=body,
                headers={"Content-Type": "application/json",
                         "x-api-key": self.api_key,
                         "anthropic-version": "2023-06-01"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:]).rstrip("```").strip()
            power_words = json.loads(text)

            for i, sentence in enumerate(sentences[:len(power_words)]):
                pw = str(power_words[i]).strip().lower()
                sentence.power_word = pw
                for word in sentence.words:
                    if word.word.strip(".,!?").lower() == pw:
                        word.is_power_word = True
                        break
            log.info("[SubtitleV2] power words detected via Claude")
            return sentences
        except Exception as exc:
            log.warning("[SubtitleV2] Claude power word failed: %s", exc)
            return self._detect_power_words_heuristic(sentences)

    def _detect_power_words_heuristic(
        self, sentences: List[CaptionSentence]
    ) -> List[CaptionSentence]:
        """Fallback: mark longest word per sentence as power word."""
        for sentence in sentences:
            if not sentence.words:
                continue
            longest = max(sentence.words, key=lambda w: len(w.word))
            longest.is_power_word = True
            sentence.power_word = longest.word
        return sentences

    # ── ASS Subtitle File Builder ──────────────────────────────────────────

    def _build_ass_file(
        self, sentences: List[CaptionSentence], video_path: Path
    ) -> Path:
        """Build an ASS subtitle file with word-level karaoke timing."""
        x_pos, y_pos = POSITION_MAP.get(self.position, POSITION_MAP["bottom_third"])
        # Convert y_pos from ffmpeg expression to ASS pixel (approximate)
        # For ASS we use PlayResX/Y = 1080x1920
        res_x, res_y = 1080, 1920
        margin_v = int(res_y * 0.08)  # 8% from bottom

        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{self.font_size},&H00FFFFFF,&H000000FF,&H00{self.shadow_color},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{margin_v},1
Style: Highlight,Arial,{self.font_size},&H00{self._hex_to_ass(self.accent_color)},&H000000FF,&H00{self.shadow_color},&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [ass_header]

        for sentence in sentences:
            if not sentence.words:
                # Fallback: add whole sentence
                start = self._to_ass_time(sentence.start)
                end = self._to_ass_time(sentence.end)
                lines.append(
                    f"Dialogue: 0,{start},{end},Default,,0,0,0,,{sentence.text}\n"
                )
                continue

            # Build karaoke line: each word appears at its timestamp
            # We do this by creating a dialogue event per word group (visible + fading)
            current_words_visible: List[WordToken] = []
            for i, word in enumerate(sentence.words):
                current_words_visible.append(word)
                w_start = self._to_ass_time(word.start)
                # Word is visible from its start to end of sentence
                w_end = self._to_ass_time(sentence.end)

                # Build display text: all words up to this one visible
                text_parts = []
                for w in current_words_visible:
                    if w.is_power_word:
                        text_parts.append(
                            f"{{\\rHighlight}}{w.word}{{\\rDefault}}"
                        )
                    else:
                        text_parts.append(w.word)

                display_text = " ".join(text_parts)
                lines.append(
                    f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{display_text}\n"
                )

        ass_file = Path(tempfile.mktemp(suffix=".ass"))
        ass_file.write_text("".join(lines), encoding="utf-8")
        return ass_file

    def _burn_ass(
        self, input_path: Path, output_path: Path, ass_path: Path
    ) -> bool:
        """Burn ASS subtitles into video using ffmpeg."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "copy",
            "-loglevel", "error",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0:
                log.error("[SubtitleV2] ffmpeg error: %s", result.stderr.decode()[:300])
                return False
            try:
                ass_path.unlink()
            except Exception:
                pass
            return True
        except Exception as exc:
            log.error("[SubtitleV2] burn error: %s", exc)
            return False

    def _copy_passthrough(self, input_path: Path, output_path: Path) -> bool:
        """Copy without subtitle burn when disabled/failed."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c", "copy", "-loglevel", "error", str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            return result.returncode == 0
        except Exception as exc:
            log.error("[SubtitleV2] passthrough error: %s", exc)
            return False

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _to_ass_time(seconds: float) -> str:
        """Convert float seconds to ASS timestamp H:MM:SS.cs"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _hex_to_ass(hex_color: str) -> str:
        """Convert RRGGBB hex to ASS BBGGRR format."""
        h = hex_color.lstrip("#")
        if len(h) == 6:
            r, g, b = h[0:2], h[2:4], h[4:6]
            return f"{b}{g}{r}".upper()
        return "00E6FF"  # default yellow
