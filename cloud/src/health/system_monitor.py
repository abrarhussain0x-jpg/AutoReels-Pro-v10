"""
system_monitor.py — Live CPU/RAM/Disk monitoring with auto-pause.
Pauses the pipeline when system resources are critically low.
Logs resource snapshots every 5 min to system_health.db.
Sends Telegram alert when any threshold is breached.
"""
from __future__ import annotations
import logging, sqlite3, time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    cpu_pct     REAL NOT NULL DEFAULT 0,
    ram_pct     REAL NOT NULL DEFAULT 0,
    disk_pct    REAL NOT NULL DEFAULT 0,
    disk_free_gb REAL NOT NULL DEFAULT 0,
    ffmpeg_procs INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class SystemHealth:
    cpu_pct: float
    ram_pct: float
    disk_pct: float
    disk_free_gb: float
    ffmpeg_procs: int
    ok: bool
    reason: str = ""


class SystemMonitor:
    """
    Monitors CPU/RAM/Disk and pauses pipeline when resources are low.
    Needs psutil: pip install psutil
    """

    # Thresholds — pipeline pauses if any is breached
    CPU_MAX  = 90.0   # %
    RAM_MAX  = 85.0   # %
    DISK_MIN = 1.0    # GB free

    def __init__(self, db_path: Path, notifier=None):
        self.db_path  = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.notifier = notifier
        self._last_alert = 0.0

        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[SysMonitor] init thresholds cpu=%.0f%% ram=%.0f%% disk=%.1fGB",
                 self.CPU_MAX, self.RAM_MAX, self.DISK_MIN)

    def check(self) -> SystemHealth:
        """Check system health right now. Returns SystemHealth."""
        try:
            import psutil
            cpu  = psutil.cpu_percent(interval=1)
            ram  = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/")
            disk_free_gb = disk.free / 1e9
            disk_pct     = disk.percent

            # Count running ffmpeg processes
            ffmpeg_count = sum(1 for p in psutil.process_iter(["name"])
                               if "ffmpeg" in (p.info["name"] or "").lower())
        except ImportError:
            log.debug("[SysMonitor] psutil not installed — skipping resource check")
            return SystemHealth(0, 0, 0, 999, 0, True, "psutil not installed")
        except Exception as e:
            log.debug("[SysMonitor] check error: %s", e)
            return SystemHealth(0, 0, 0, 999, 0, True)

        # Determine if pipeline should pause
        ok = True
        reason = ""
        if cpu > self.CPU_MAX:
            ok = False
            reason = f"CPU {cpu:.0f}% > {self.CPU_MAX:.0f}%"
        elif ram > self.RAM_MAX:
            ok = False
            reason = f"RAM {ram:.0f}% > {self.RAM_MAX:.0f}%"
        elif disk_free_gb < self.DISK_MIN:
            ok = False
            reason = f"Disk {disk_free_gb:.1f}GB free < {self.DISK_MIN}GB"

        health = SystemHealth(cpu, ram, disk_pct, disk_free_gb, ffmpeg_count, ok, reason)

        # Save snapshot
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO snapshots (ts, cpu_pct, ram_pct, disk_pct, disk_free_gb, ffmpeg_procs)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (time.time(), cpu, ram, disk_pct, disk_free_gb, ffmpeg_count))
        except Exception:
            pass

        # Alert on breach (max once per 30 min)
        if not ok and time.time() - self._last_alert > 1800:
            self._last_alert = time.time()
            if self.notifier:
                self.notifier.send(f"⚠️ AutoReels resource alert: {reason}")
            log.warning("[SysMonitor] resource breach: %s", reason)

        return health

    def wait_until_ok(self, max_wait: int = 600) -> bool:
        """Block until system resources are healthy. Returns False if timed out."""
        for _ in range(max_wait // 30):
            health = self.check()
            if health.ok:
                return True
            log.info("[SysMonitor] waiting for resources (%s)...", health.reason)
            time.sleep(30)
        log.error("[SysMonitor] timed out waiting for resources")
        return False

    def status(self) -> str:
        h = self.check()
        status = "✅ OK" if h.ok else f"❌ {h.reason}"
        return (f"=== SYSTEM HEALTH ===\n"
                f"  CPU:       {h.cpu_pct:.1f}%\n"
                f"  RAM:       {h.ram_pct:.1f}%\n"
                f"  Disk free: {h.disk_free_gb:.1f} GB\n"
                f"  FFmpeg:    {h.ffmpeg_procs} running\n"
                f"  Status:    {status}")

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
