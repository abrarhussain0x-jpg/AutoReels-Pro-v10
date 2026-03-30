"""
thumbnail_generator.py — Real PIL thumbnail generator.
Creates professional branded thumbnails for every clip.
6 themes: classic, neon, dark, minimal, fire, golden.
No API needed. Pure Pillow.
"""
from __future__ import annotations
import logging, textwrap
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

THEMES = {
    "classic": {
        "bg": (15, 15, 25),         "text": (255, 255, 255),
        "accent": (255, 50, 50),    "bar": (220, 30, 30),
        "shadow": (0, 0, 0),
    },
    "neon": {
        "bg": (5, 5, 20),           "text": (0, 255, 200),
        "accent": (255, 0, 255),    "bar": (0, 200, 255),
        "shadow": (0, 100, 100),
    },
    "dark": {
        "bg": (10, 10, 10),         "text": (240, 240, 240),
        "accent": (255, 200, 0),    "bar": (200, 150, 0),
        "shadow": (0, 0, 0),
    },
    "minimal": {
        "bg": (240, 240, 240),      "text": (20, 20, 20),
        "accent": (255, 60, 0),     "bar": (255, 60, 0),
        "shadow": (180, 180, 180),
    },
    "fire": {
        "bg": (20, 5, 0),           "text": (255, 230, 200),
        "accent": (255, 100, 0),    "bar": (255, 50, 0),
        "shadow": (100, 20, 0),
    },
    "golden": {
        "bg": (10, 8, 0),           "text": (255, 245, 180),
        "accent": (255, 200, 0),    "bar": (200, 150, 0),
        "shadow": (80, 60, 0),
    },
}

W, H = 1080, 1920   # 9:16 portrait


class ThumbnailGenerator:
    """Creates branded 9:16 thumbnails from video frames + text."""

    def __init__(self, channel_name: str = "AutoReels", theme: str = "classic"):
        self.channel = channel_name
        self.theme   = THEMES.get(theme, THEMES["classic"])
        self._font_cache = {}

    def generate(
        self,
        frame_path: Optional[Path],
        hook_text: str,
        title: str,
        clip_index: int,
        output_path: Path,
    ) -> bool:
        """
        Generate a thumbnail. frame_path can be None (solid bg used).
        Returns True on success.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
        except ImportError:
            log.warning("[Thumb] Pillow not installed — skip thumbnail")
            return False

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        t = self.theme

        # ── Base image ────────────────────────────────────────────────────────
        if frame_path and Path(frame_path).exists():
            try:
                img = Image.open(frame_path).convert("RGB")
                img = self._fit_cover(img, W, H)
                img = ImageEnhance.Brightness(img).enhance(0.55)
                img = ImageEnhance.Contrast(img).enhance(1.3)
            except Exception:
                img = Image.new("RGB", (W, H), t["bg"])
        else:
            img = Image.new("RGB", (W, H), t["bg"])

        draw = ImageDraw.Draw(img, "RGBA")

        # ── Top gradient bar (hook area) ──────────────────────────────────────
        for y in range(320):
            alpha = int(220 * (1 - y / 320))
            draw.rectangle([(0, y), (W, y + 1)], fill=(*t["bg"], alpha))

        # ── Bottom gradient (title area) ──────────────────────────────────────
        for y in range(H - 600, H):
            alpha = int(240 * ((y - (H - 600)) / 600))
            draw.rectangle([(0, y), (W, y + 1)], fill=(*t["bg"], alpha))

        # ── Accent bar (left edge) ────────────────────────────────────────────
        draw.rectangle([(0, 0), (12, H)], fill=t["bar"])

        # ── Hook text (top, ALL CAPS) ─────────────────────────────────────────
        hook_font = self._font(80, bold=True)
        hook_clean = hook_text.upper()[:28]
        self._draw_text_shadow(draw, hook_clean, hook_font, W // 2, 80,
                               t["text"], t["shadow"], anchor="mm")

        # ── Part badge ────────────────────────────────────────────────────────
        badge_text = f"PART {clip_index:02d}"
        badge_font = self._font(52, bold=True)
        bw = 220; bh = 70; bx = W - bw - 30; by = 30
        draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)],
                                radius=16, fill=t["bar"])
        draw.text((bx + bw // 2, by + bh // 2), badge_text,
                  font=badge_font, fill=(255, 255, 255), anchor="mm")

        # ── Title (bottom, word-wrapped) ──────────────────────────────────────
        title_font  = self._font(58, bold=True)
        title_lines = textwrap.wrap(title[:60], width=22)[:3]
        ty = H - 300
        for line in title_lines:
            self._draw_text_shadow(draw, line, title_font, W // 2, ty,
                                   t["text"], t["shadow"], anchor="mm")
            ty += 72

        # ── Channel watermark ─────────────────────────────────────────────────
        ch_font = self._font(38)
        draw.text((W // 2, H - 65), f"@{self.channel}",
                  font=ch_font, fill=(*t["accent"], 200), anchor="mm")

        # ── Save ──────────────────────────────────────────────────────────────
        img.save(str(output_path), "JPEG", quality=92, optimize=True)
        log.info("[Thumb] generated %s (theme=%s)", output_path.name,
                 [k for k, v in THEMES.items() if v == self.theme][0] if self.theme in THEMES.values() else "custom")
        return True

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _font(self, size: int, bold: bool = False):
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        from PIL import ImageFont
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for fp in font_paths:
            try:
                font = ImageFont.truetype(fp, size)
                self._font_cache[key] = font
                return font
            except Exception:
                continue
        font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    @staticmethod
    def _fit_cover(img, w: int, h: int):
        from PIL import Image
        img_ratio    = img.width / img.height
        target_ratio = w / h
        if img_ratio > target_ratio:
            new_h = h
            new_w = int(h * img_ratio)
        else:
            new_w = w
            new_h = int(w / img_ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top  = (new_h - h) // 2
        return img.crop((left, top, left + w, top + h))

    @staticmethod
    def _draw_text_shadow(draw, text, font, x, y, color, shadow_color, anchor="mm"):
        for dx, dy in [(-3, 3), (3, 3), (0, 4), (0, 0)]:
            col = shadow_color if (dx, dy) != (0, 0) else color
            draw.text((x + dx, y + dy), text, font=font, fill=col, anchor=anchor)
