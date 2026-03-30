"""
job_queue.py — Persistent SQLite job queue with dedup + priority.
Tracks every video through the pipeline. Prevents re-processing.
Supports priority levels: HIGH (viral/fast-track) > NORMAL > LOW.
"""
from __future__ import annotations
import json, logging, sqlite3, time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL DEFAULT '',
    channel     TEXT    NOT NULL DEFAULT '',
    state       TEXT    NOT NULL DEFAULT 'PENDING',
    priority    INTEGER NOT NULL DEFAULT 5,
    score       REAL    NOT NULL DEFAULT 0.0,
    niche       TEXT    NOT NULL DEFAULT 'movie',
    clips_total INTEGER NOT NULL DEFAULT 0,
    clips_done  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL    NOT NULL,
    started_at  REAL    NOT NULL DEFAULT 0,
    finished_at REAL    NOT NULL DEFAULT 0,
    error       TEXT    NOT NULL DEFAULT '',
    meta_json   TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jobs_state    ON jobs(state, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id);

CREATE TABLE IF NOT EXISTS processed_ids (
    video_id   TEXT PRIMARY KEY,
    processed_at REAL NOT NULL
);
"""

class JobState:
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    DONE       = "DONE"
    FAILED     = "FAILED"
    SKIPPED    = "SKIPPED"
    DEFERRED   = "DEFERRED"

class Priority(IntEnum):
    HIGH   = 1
    NORMAL = 5
    LOW    = 9

@dataclass
class Job:
    id: int
    video_id: str
    title: str
    url: str
    channel: str
    state: str
    priority: int
    score: float
    niche: str
    clips_total: int
    clips_done: int
    created_at: float
    meta: dict


class JobQueue:
    """Thread-safe SQLite job queue with deduplication."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[Queue] init db=%s", self.db_path)

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(self, video_id: str, title: str, url: str, channel: str,
                score: float = 0.5, niche: str = "movie",
                priority: int = Priority.NORMAL, meta: dict = None) -> bool:
        """Add a job. Returns False if already exists or recently processed."""
        if self.already_processed(video_id):
            log.debug("[Queue] skip %s — already done", video_id)
            return False

        with self._conn() as c:
            try:
                c.execute("""
                    INSERT OR IGNORE INTO jobs
                    (video_id, title, url, channel, state, priority, score, niche,
                     created_at, meta_json)
                    VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
                """, (video_id, title, url, channel, priority, score, niche,
                      time.time(), json.dumps(meta or {})))
                inserted = c.execute(
                    "SELECT changes()"
                ).fetchone()[0]
                if inserted:
                    log.info("[Queue] enqueued %s (score=%.3f pri=%d)", video_id, score, priority)
                return bool(inserted)
            except Exception as e:
                log.error("[Queue] enqueue error: %s", e)
                return False

    def fast_track(self, video_id: str):
        """Promote a job to HIGH priority (viral fast-track)."""
        with self._conn() as c:
            c.execute("UPDATE jobs SET priority=? WHERE video_id=?",
                      (Priority.HIGH, video_id))
        log.info("[Queue] fast-tracked %s to HIGH priority", video_id)

    # ── Dequeue ──────────────────────────────────────────────────────────────

    def next_pending(self) -> Optional[Job]:
        """Get the next job to process (highest priority, oldest first)."""
        with self._conn() as c:
            row = c.execute("""
                SELECT id, video_id, title, url, channel, state, priority,
                       score, niche, clips_total, clips_done, created_at, meta_json
                FROM jobs WHERE state='PENDING'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
            """).fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def pending(self, limit: int = 10) -> List[Job]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT id, video_id, title, url, channel, state, priority,
                       score, niche, clips_total, clips_done, created_at, meta_json
                FROM jobs WHERE state='PENDING'
                ORDER BY priority ASC, created_at ASC LIMIT ?
            """, (limit,)).fetchall()
        return [self._row_to_job(r) for r in rows]

    # ── State Updates ─────────────────────────────────────────────────────────

    def mark_processing(self, video_id: str, clips_total: int = 0):
        with self._conn() as c:
            c.execute("""UPDATE jobs SET state='PROCESSING', started_at=?, clips_total=?
                         WHERE video_id=?""", (time.time(), clips_total, video_id))

    def mark_done(self, video_id: str, clips_done: int = 0):
        with self._conn() as c:
            c.execute("""UPDATE jobs SET state='DONE', finished_at=?, clips_done=?
                         WHERE video_id=?""", (time.time(), clips_done, video_id))
            c.execute("INSERT OR REPLACE INTO processed_ids (video_id, processed_at) VALUES (?,?)",
                      (video_id, time.time()))
        log.info("[Queue] ✅ done %s (%d clips)", video_id, clips_done)

    def mark_failed(self, video_id: str, error: str = ""):
        with self._conn() as c:
            c.execute("""UPDATE jobs SET state='FAILED', finished_at=?, error=?
                         WHERE video_id=?""", (time.time(), error[:500], video_id))
        log.warning("[Queue] ❌ failed %s: %s", video_id, error[:100])

    def mark_skipped(self, video_id: str, reason: str = ""):
        with self._conn() as c:
            c.execute("""UPDATE jobs SET state='SKIPPED', finished_at=?, error=?
                         WHERE video_id=?""", (time.time(), reason[:200], video_id))
            c.execute("INSERT OR REPLACE INTO processed_ids (video_id, processed_at) VALUES (?,?)",
                      (video_id, time.time()))

    def already_processed(self, video_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM processed_ids WHERE video_id=?", (video_id,)
            ).fetchone()
        return row is not None

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute("""
                SELECT state, COUNT(*) FROM jobs GROUP BY state
            """).fetchall()
        return {r[0]: r[1] for r in rows}

    def recent_jobs(self, limit: int = 20) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT video_id, title, state, priority, score, clips_done,
                       created_at, finished_at, error
                FROM jobs ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        cols = ["video_id","title","state","priority","score","clips_done",
                "created_at","finished_at","error"]
        return [dict(zip(cols, r)) for r in rows]

    def queue_report(self) -> str:
        stats = self.stats()
        lines = ["=== JOB QUEUE STATUS ===\n"]
        for state, count in stats.items():
            lines.append(f"  {state:<12} {count}")
        recent = self.recent_jobs(10)
        if recent:
            lines.append("\nRecent jobs:")
            for j in recent:
                age = (time.time() - j["created_at"]) / 3600
                lines.append(f"  [{j['state']:<10}] {j['title'][:40]:<40} "
                              f"clips={j['clips_done']} age={age:.1f}h")
        return "\n".join(lines)

    # ── Utils ─────────────────────────────────────────────────────────────────

    def _row_to_job(self, row) -> Job:
        meta = {}
        try:
            meta = json.loads(row[12])
        except Exception:
            pass
        return Job(id=row[0], video_id=row[1], title=row[2], url=row[3],
                   channel=row[4], state=row[5], priority=row[6],
                   score=row[7], niche=row[8], clips_total=row[9],
                   clips_done=row[10], created_at=row[11], meta=meta)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
