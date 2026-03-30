"""
thumbnail_ab.py v10.0 — Thumbnail A/B Testing Engine.

Generates 3 thumbnail variants per clip and learns which style
drives the highest CTR per niche. Tracks results in thumbnail_ab.db.

Variant A: Face-centered gradient overlay + hook text (top)
Variant B: High-contrast action frame + bold title bottom
Variant C: Blurred background + centered text + emoji accent

New in v10:
  - 3 distinct visual styles per clip
  - CTR tracking after 24h (Facebook link click data)
  - UCB1 weight update per niche after each data point
  - auto-selects winning style for next video
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS thumbnail_variants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT    NOT NULL,
    clip_num        INTEGER NOT NULL DEFAULT 1,
    platform        TEXT    NOT NULL,
    niche           TEXT    NOT NULL,
    variant         TEXT    NOT NULL,
    file_path       TEXT    NOT NULL,
    post_id         TEXT    NOT NULL DEFAULT '',
    uploaded_at     REAL    NOT NULL DEFAULT 0,
    clicks          INTEGER NOT NULL DEFAULT 0,
    impressions     INTEGER NOT NULL DEFAULT 0,
    ctr             REAL    NOT NULL DEFAULT 0.0,
    is_winner       INTEGER NOT NULL DEFAULT 0,
    metrics_pulled  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS variant_weights (
    niche       TEXT    NOT NULL,
    variant     TEXT    NOT NULL,
    weight      REAL    NOT NULL DEFAULT 1.0,
    wins        INTEGER NOT NULL DEFAULT 0,
    trials      INTEGER NOT NULL DEFAULT 0,
    avg_ctr     REAL    NOT NULL DEFAULT 0.0,
    updated_at  REAL    NOT NULL,
    PRIMARY KEY (niche, variant)
);

CREATE INDEX IF NOT EXISTS idx_tv_video ON thumbnail_variants(video_id, clip_num);
"""

VARIANTS = ["A", "B", "C"]
EXPLORATION_FACTOR = 1.5


@dataclass
class ThumbnailVariant:
    variant: str       # A | B | C
    file_path: Path
    style: str         # face_overlay | contrast_title | blur_center


class ThumbnailABEngine:
    """Generates and tracks A/B thumbnail variants per niche."""

    def __init__(
        self,
        db_path: Path,
        enabled: bool = True,
        n_variants: int = 3,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.n_variants = min(n_variants, 3)

        with self._conn() as c:
            c.executescript(SCHEMA)
        self._init_weights()
        log.info("[ThumbnailAB] init enabled=%s variants=%d", enabled, self.n_variants)

    # ── Public API ──────────────────────────────────────────────────────────

    def generate_variants(
        self,
        frame_path: Path,
        hook_text: str,
        title: str,
        niche: str,
        output_dir: Path,
    ) -> List[ThumbnailVariant]:
        """Generate N thumbnail variants from a video frame."""
        variants = []
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not self.enabled:
            # Just copy frame as-is for variant A
            out = output_dir / "thumb_A.jpg"
            try:
                import shutil
                shutil.copy(frame_path, out)
            except Exception:
                pass
            return [ThumbnailVariant("A", out, "passthrough")]

        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter
            img = Image.open(frame_path).convert("RGB")
            img = img.resize((1080, 1920), Image.LANCZOS)
        except Exception as exc:
            log.warning("[ThumbnailAB] PIL error: %s", exc)
            return []

        for variant in VARIANTS[:self.n_variants]:
            out_path = output_dir / f"thumb_{variant}.jpg"
            try:
                rendered = self._render_variant(img.copy(), variant, hook_text, title)
                rendered.save(str(out_path), "JPEG", quality=92)
                style = {"A": "face_overlay", "B": "contrast_title", "C": "blur_center"}[variant]
                variants.append(ThumbnailVariant(variant=variant, file_path=out_path, style=style))
                log.debug("[ThumbnailAB] rendered variant %s → %s", variant, out_path.name)
            except Exception as exc:
                log.warning("[ThumbnailAB] variant %s render error: %s", variant, exc)

        return variants

    def get_best_variant(self, niche: str) -> str:
        """UCB1-select the best thumbnail variant for this niche."""
        weights = self._load_weights(niche)
        if not weights:
            return "A"
        total_trials = sum(w["trials"] for w in weights.values())
        best_v = "A"
        best_score = -1.0
        for variant, w in weights.items():
            if w["trials"] == 0:
                return variant  # explore untried
            exploit = w["weight"]
            explore = EXPLORATION_FACTOR * math.sqrt(math.log(max(1, total_trials)) / w["trials"])
            score = exploit + explore
            if score > best_score:
                best_score = score
                best_v = variant
        return best_v

    def record_result(
        self,
        video_id: str,
        clip_num: int,
        variant: str,
        platform: str,
        niche: str,
        clicks: int,
        impressions: int,
    ) -> None:
        ctr = clicks / max(1, impressions) * 100
        with self._conn() as c:
            c.execute("""
                UPDATE thumbnail_variants
                SET clicks=?, impressions=?, ctr=?, metrics_pulled=1
                WHERE video_id=? AND clip_num=? AND variant=? AND platform=?
            """, (clicks, impressions, ctr, video_id, clip_num, variant, platform))
        self._recompute_weights(niche)
        log.info("[ThumbnailAB] recorded %s/%s var=%s CTR=%.2f%%", video_id, clip_num, variant, ctr)

    def register_upload(
        self,
        video_id: str,
        clip_num: int,
        variant: str,
        platform: str,
        niche: str,
        file_path: str,
        post_id: str = "",
    ) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO thumbnail_variants
                (video_id, clip_num, platform, niche, variant, file_path, post_id, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (video_id, clip_num, platform, niche, variant, file_path, post_id, time.time()))

    def report(self) -> str:
        with self._conn() as c:
            rows = c.execute("""
                SELECT niche, variant, wins, trials, avg_ctr, weight
                FROM variant_weights ORDER BY niche, weight DESC
            """).fetchall()
        lines = ["=== THUMBNAIL A/B REPORT ===\n"]
        if not rows:
            lines.append("  No data yet.")
        for r in rows:
            niche, variant, wins, trials, avg_ctr, weight = r
            lines.append(
                f"  {niche:<12} | Variant {variant} | wins={wins}/{trials} "
                f"| CTR={avg_ctr:.2f}% | weight={weight:.3f}"
            )
        return "\n".join(lines)

    # ── Rendering ──────────────────────────────────────────────────────────

    def _render_variant(self, img, variant: str, hook: str, title: str):
        """Render a thumbnail variant with PIL."""
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        draw = ImageDraw.Draw(img)
        w, h = img.size

        # Try to load a font, fallback to default
        try:
            font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
            font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        except Exception:
            font_big = ImageFont.load_default()
            font_med = font_big

        if variant == "A":
            # Gradient overlay at bottom, hook text at top
            overlay = Image.new("RGBA", (w, h // 2), (0, 0, 0, 160))
            img.paste(Image.fromarray(
                __import__("numpy").array(overlay, dtype="uint8")
            ), (0, h // 2), mask=None) if False else None
            # Simple gradient rectangle
            for i in range(h // 2, h):
                alpha = int(160 * (i - h // 2) / (h // 2))
                draw.rectangle([(0, i), (w, i + 1)], fill=(0, 0, 0, alpha))
            draw.text((w // 2, 80), hook[:28], font=font_big, fill=(255, 230, 0),
                      anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))
            draw.text((w // 2, h - 120), title[:40], font=font_med, fill=(255, 255, 255),
                      anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))

        elif variant == "B":
            # High contrast: darken image, white title at bottom
            from PIL import ImageEnhance
            img = ImageEnhance.Contrast(img).enhance(1.4)
            img = ImageEnhance.Brightness(img).enhance(0.8)
            draw = ImageDraw.Draw(img)
            draw.rectangle([(0, h - 200), (w, h)], fill=(0, 0, 0, 200))
            draw.text((w // 2, h - 100), title[:40], font=font_big, fill=(255, 255, 255),
                      anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))

        elif variant == "C":
            # Blurred background + centered text
            blurred = img.filter(ImageFilter.GaussianBlur(radius=12))
            img.paste(blurred)
            draw = ImageDraw.Draw(img)
            draw.rectangle([(w // 6, h // 3), (w * 5 // 6, h * 2 // 3)],
                           fill=(0, 0, 0, 180))
            draw.text((w // 2, h // 2 - 60), hook[:28], font=font_big, fill=(255, 230, 0),
                      anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
            draw.text((w // 2, h // 2 + 60), title[:35], font=font_med, fill=(255, 255, 255),
                      anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))

        return img

    # ── Weights ────────────────────────────────────────────────────────────

    def _init_weights(self) -> None:
        niches = ["movie", "anime", "kdrama", "horror", "documentary", "general"]
        now = time.time()
        with self._conn() as c:
            for niche in niches:
                for v in VARIANTS:
                    c.execute("""
                        INSERT OR IGNORE INTO variant_weights
                        (niche, variant, weight, wins, trials, avg_ctr, updated_at)
                        VALUES (?, ?, 1.0, 0, 0, 0.0, ?)
                    """, (niche, v, now))

    def _load_weights(self, niche: str) -> Dict[str, dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT variant, weight, wins, trials, avg_ctr FROM variant_weights WHERE niche=?
            """, (niche,)).fetchall()
        return {r[0]: {"weight": r[1], "wins": r[2], "trials": r[3], "avg_ctr": r[4]}
                for r in rows}

    def _recompute_weights(self, niche: str) -> None:
        with self._conn() as c:
            rows = c.execute("""
                SELECT variant, AVG(ctr), COUNT(*), SUM(CASE WHEN ctr = MAX(ctr) THEN 1 ELSE 0 END)
                FROM thumbnail_variants WHERE niche=? AND metrics_pulled=1
                GROUP BY variant
            """, (niche,)).fetchall()
            if not rows:
                return
            max_ctr = max(r[1] or 0 for r in rows) or 1.0
            for variant, avg_ctr, trials, wins in rows:
                weight = max(0.1, (avg_ctr or 0) / max_ctr)
                c.execute("""
                    UPDATE variant_weights SET weight=?, trials=?, avg_ctr=?, updated_at=?
                    WHERE niche=? AND variant=?
                """, (weight, trials, avg_ctr or 0, time.time(), niche, variant))

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
