"""
cleanup.py — Auto-cleanup old temp files to keep disk free.
Deletes processed video files, raw downloads older than X hours.
Keeps SQLite databases and logs intact.
Runs automatically after each pipeline cycle.
"""
from __future__ import annotations
import logging, shutil, time
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)


class AutoCleanup:

    def __init__(self, base_dir: Path,
                 cleanup_after_hours: int = 72,
                 min_free_gb: float = 2.0):
        self.base_dir            = Path(base_dir)
        self.cleanup_after_hours = cleanup_after_hours
        self.min_free_gb         = min_free_gb
        self.max_age_s           = cleanup_after_hours * 3600

    def run(self, force: bool = False) -> dict:
        """Run cleanup. Returns dict with stats."""
        stats = {"files_deleted": 0, "bytes_freed": 0, "dirs_deleted": 0}

        # Always clean processed clip files
        clips_freed = self._clean_dir(
            self.base_dir / "tmp", patterns=["*.mp4","*.mkv","*.webm","*.jpg","*.png"],
            max_age_s=self.max_age_s if not force else 0,
        )
        stats["files_deleted"] += clips_freed[0]
        stats["bytes_freed"]   += clips_freed[1]

        # Clean empty subdirectories
        stats["dirs_deleted"] += self._clean_empty_dirs(self.base_dir / "tmp")

        # Emergency cleanup if disk is very low
        if self._disk_free_gb() < self.min_free_gb:
            log.warning("[Cleanup] LOW DISK (%.1f GB) — emergency cleanup!", self._disk_free_gb())
            emergency = self._clean_dir(
                self.base_dir / "tmp",
                patterns=["*.mp4","*.mkv","*.webm"],
                max_age_s=3600,  # anything older than 1h
            )
            stats["files_deleted"] += emergency[0]
            stats["bytes_freed"]   += emergency[1]

        freed_mb = stats["bytes_freed"] / 1e6
        if stats["files_deleted"] > 0:
            log.info("[Cleanup] deleted %d files, freed %.1f MB",
                     stats["files_deleted"], freed_mb)
        return stats

    def _clean_dir(self, directory: Path, patterns: List[str],
                   max_age_s: int) -> tuple:
        """Delete files matching patterns older than max_age_s. Returns (count, bytes)."""
        directory = Path(directory)
        if not directory.exists():
            return 0, 0

        count = 0
        total_bytes = 0
        now = time.time()

        for pattern in patterns:
            for f in directory.rglob(pattern):
                try:
                    age = now - f.stat().st_mtime
                    if age > max_age_s:
                        size = f.stat().st_size
                        f.unlink()
                        count += 1
                        total_bytes += size
                        log.debug("[Cleanup] deleted %s (age=%.0fh)", f.name, age / 3600)
                except Exception as e:
                    log.debug("[Cleanup] error deleting %s: %s", f, e)

        return count, total_bytes

    def _clean_empty_dirs(self, directory: Path) -> int:
        """Remove empty subdirectories. Returns count deleted."""
        if not directory.exists():
            return 0
        count = 0
        for d in sorted(directory.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()   # only works if empty
                    count += 1
                except OSError:
                    pass
        return count

    def _disk_free_gb(self) -> float:
        try:
            import shutil
            _, _, free = shutil.disk_usage(self.base_dir)
            return free / 1e9
        except Exception:
            return 999.0

    def status(self) -> str:
        free = self._disk_free_gb()
        age_h = self.cleanup_after_hours
        return (f"=== CLEANUP CONFIG ===\n"
                f"  Cleanup after: {age_h}h\n"
                f"  Min free disk: {self.min_free_gb} GB\n"
                f"  Current free:  {free:.1f} GB\n"
                f"  Status: {'✅ OK' if free > self.min_free_gb else '⚠️ LOW DISK'}")
