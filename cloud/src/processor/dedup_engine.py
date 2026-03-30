"""
dedup_engine.py — Perceptual hash deduplication for video clips.
Extracts a frame from each clip, computes pHash, stores in SQLite.
Prevents uploading near-duplicate clips (same scene, different trim).
Threshold: hamming distance <= 8 = duplicate (configurable).
"""
from __future__ import annotations
import logging, sqlite3, subprocess, tempfile, time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS clip_hashes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_path   TEXT    NOT NULL,
    video_id    TEXT    NOT NULL,
    clip_num    INTEGER NOT NULL DEFAULT 1,
    phash       TEXT    NOT NULL,
    added_at    REAL    NOT NULL,
    UNIQUE(video_id, clip_num)
);
CREATE INDEX IF NOT EXISTS idx_hash ON clip_hashes(phash);
"""


class DedupEngine:
    """Perceptual hash deduplication. Needs Pillow + imagehash."""

    def __init__(self, db_path: Path, threshold: int = 8):
        self.db_path   = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[Dedup] init threshold=%d hammingdist", threshold)

    def is_duplicate(self, clip_path: Path) -> bool:
        """Returns True if this clip is too similar to an already-stored clip."""
        phash = self._compute_phash(clip_path)
        if not phash:
            return False   # can't hash = allow through

        stored = self._load_all_hashes()
        new_hash = self._parse_hash(phash)
        if new_hash is None:
            return False

        for stored_hash_str in stored:
            stored_hash = self._parse_hash(stored_hash_str)
            if stored_hash is None:
                continue
            dist = bin(new_hash ^ stored_hash).count("1")
            if dist <= self.threshold:
                log.info("[Dedup] DUPLICATE detected (dist=%d <= %d)", dist, self.threshold)
                return True
        return False

    def register(self, clip_path: Path, video_id: str, clip_num: int) -> bool:
        """Store clip hash after confirming it's not a duplicate."""
        phash = self._compute_phash(clip_path)
        if not phash:
            return False
        with self._conn() as c:
            try:
                c.execute("""
                    INSERT OR REPLACE INTO clip_hashes
                    (clip_path, video_id, clip_num, phash, added_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(clip_path), video_id, clip_num, phash, time.time()))
                return True
            except Exception as e:
                log.debug("[Dedup] register error: %s", e)
                return False

    def _compute_phash(self, clip_path: Path) -> Optional[str]:
        """Extract middle frame from clip and compute perceptual hash."""
        try:
            # Get duration
            dur_cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)]
            r = subprocess.run(dur_cmd, capture_output=True, text=True, timeout=10)
            duration = float(r.stdout.strip() or "10")
            seek_t   = duration / 2

            # Extract frame
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                frame_path = tf.name

            frame_cmd = [
                "ffmpeg", "-y", "-ss", str(seek_t), "-i", str(clip_path),
                "-frames:v", "1", "-vf", "scale=64:64",
                "-loglevel", "error", frame_path,
            ]
            subprocess.run(frame_cmd, capture_output=True, timeout=15)

            # Compute pHash
            from PIL import Image
            import imagehash
            img   = Image.open(frame_path).convert("L")
            phash = str(imagehash.phash(img))
            Path(frame_path).unlink(missing_ok=True)
            return phash

        except ImportError:
            log.debug("[Dedup] Pillow/imagehash not installed — skipping dedup")
            return None
        except Exception as e:
            log.debug("[Dedup] phash error: %s", e)
            return None

    def _load_all_hashes(self):
        with self._conn() as c:
            rows = c.execute("SELECT phash FROM clip_hashes").fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _parse_hash(phash_str: str) -> Optional[int]:
        try:
            return int(phash_str, 16)
        except Exception:
            return None

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=15)
