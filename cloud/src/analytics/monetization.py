"""
monetization.py — Facebook monetization tracker.

Tracks your earnings from:
  - Reels Play Bonus (Facebook pays per 1000 plays)
  - In-Stream Ads revenue (if eligible)
  - Stars received from fans
  - Estimates monthly earnings from current performance

Shows you exactly how much you're earning and what you need
to do to earn more.
"""
from __future__ import annotations
import json, logging, sqlite3, time, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS earnings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    period      TEXT NOT NULL,
    source      TEXT NOT NULL,
    amount_usd  REAL NOT NULL DEFAULT 0.0,
    plays       INTEGER NOT NULL DEFAULT 0,
    recorded_at REAL NOT NULL
);
"""

# Facebook Reels Play Bonus estimated rates (varies by region/niche)
REELS_BONUS_RATE_PER_1K = {
    "US":  8.50,   # $8.50 per 1,000 plays (US audience)
    "UK":  6.00,
    "CA":  5.50,
    "AU":  5.00,
    "IN":  0.80,   # Lower CPM for India
    "DEFAULT": 3.00,
}

# Monetization requirements
REQUIREMENTS = {
    "reels_bonus": {
        "followers": 10_000,
        "plays_30d": 600_000,
        "description": "Reels Play Bonus Program",
    },
    "instream_ads": {
        "followers": 10_000,
        "views_1min_30d": 600_000,
        "description": "In-Stream Ads",
    },
    "stars": {
        "followers": 500,
        "description": "Facebook Stars (fan support)",
    },
}


@dataclass
class EarningsEstimate:
    monthly_plays: int
    estimated_monthly_usd: float
    daily_average_usd: float
    annual_projection_usd: float
    eligible_programs: list
    next_milestone: str
    plays_needed_for_bonus: int


class MonetizationTracker:
    """Tracks and estimates Facebook monetization earnings."""

    def __init__(self, db_path: Path, access_token: str = "",
                 page_id: str = "", audience_country: str = "US"):
        self.db_path  = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.token    = access_token
        self.page_id  = page_id
        self.country  = audience_country
        self.cpm_rate = REELS_BONUS_RATE_PER_1K.get(
            audience_country, REELS_BONUS_RATE_PER_1K["DEFAULT"]
        )
        with self._conn() as c:
            c.executescript(SCHEMA)

    def estimate_earnings(
        self,
        monthly_plays: int,
        follower_count: int,
    ) -> EarningsEstimate:
        """Calculate estimated monthly earnings from current performance."""
        eligible = []

        # Check eligibility
        if follower_count >= REQUIREMENTS["stars"]["followers"]:
            eligible.append("⭐ Facebook Stars")

        if (follower_count >= REQUIREMENTS["reels_bonus"]["followers"] and
                monthly_plays >= REQUIREMENTS["reels_bonus"]["plays_30d"]):
            eligible.append("🎬 Reels Play Bonus")

        if (follower_count >= REQUIREMENTS["instream_ads"]["followers"]):
            eligible.append("💰 In-Stream Ads (if enabled)")

        # Earnings calculation
        monthly_usd = (monthly_plays / 1000) * self.cpm_rate
        daily_avg   = monthly_usd / 30
        annual      = monthly_usd * 12

        # Next milestone
        if monthly_plays < REQUIREMENTS["reels_bonus"]["plays_30d"]:
            needed = REQUIREMENTS["reels_bonus"]["plays_30d"] - monthly_plays
            next_ms = f"Need {needed:,} more plays/month to unlock Reels Bonus"
        elif follower_count < REQUIREMENTS["reels_bonus"]["followers"]:
            needed_f = REQUIREMENTS["reels_bonus"]["followers"] - follower_count
            next_ms = f"Need {needed_f:,} more followers for Reels Bonus"
        else:
            next_ms = "✅ Eligible! Apply at facebook.com/creators/monetization"

        plays_needed = max(0, REQUIREMENTS["reels_bonus"]["plays_30d"] - monthly_plays)

        return EarningsEstimate(
            monthly_plays=monthly_plays,
            estimated_monthly_usd=round(monthly_usd, 2),
            daily_average_usd=round(daily_avg, 2),
            annual_projection_usd=round(annual, 2),
            eligible_programs=eligible,
            next_milestone=next_ms,
            plays_needed_for_bonus=plays_needed,
        )

    def record_earnings(self, period: str, source: str,
                        amount_usd: float, plays: int = 0):
        with self._conn() as c:
            c.execute("""
                INSERT INTO earnings (period, source, amount_usd, plays, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (period, source, amount_usd, plays, time.time()))
        log.info("[Monetization] recorded $%.2f from %s", amount_usd, source)

    def earnings_report(self, monthly_plays: int = 0,
                        follower_count: int = 0) -> str:
        est = self.estimate_earnings(monthly_plays, follower_count)

        lines = [
            "=== MONETIZATION TRACKER ===\n",
            f"  Audience country:   {self.country} (CPM rate: ${self.cpm_rate:.2f}/1K plays)",
            f"  Monthly plays:      {est.monthly_plays:,}",
            f"  Est. monthly earn:  ${est.estimated_monthly_usd:,.2f}",
            f"  Est. daily earn:    ${est.daily_average_usd:.2f}/day",
            f"  Annual projection:  ${est.annual_projection_usd:,.2f}/year",
            f"\n  Eligible programs:",
        ]
        if est.eligible_programs:
            for prog in est.eligible_programs:
                lines.append(f"    ✅ {prog}")
        else:
            lines.append("    ❌ Not yet eligible (keep growing!)")

        lines.append(f"\n  Next milestone: {est.next_milestone}")

        if est.plays_needed_for_bonus > 0:
            clips_needed = est.plays_needed_for_bonus // 10_000
            lines.append(f"\n  💡 You need ~{clips_needed} more clips going viral")
            lines.append(f"     to unlock the Reels Bonus this month.")

        lines.append("\n  📖 Apply at: facebook.com/creators/monetization")
        return "\n".join(lines)

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
