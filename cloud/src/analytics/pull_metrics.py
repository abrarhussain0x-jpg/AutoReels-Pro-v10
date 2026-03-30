"""
pull_metrics.py v8.0 — Engagement metrics puller.

Pulls real platform engagement 24-72h after upload.
Updates analytics DB + A/B engine.
"""

import logging
from typing import Dict

log = logging.getLogger(__name__)


class MetricsPuller:
    def __init__(self, analytics, uploaders: Dict):
        self.analytics = analytics
        self.uploaders = uploaders

    def run(self) -> int:
        pending = self.analytics.pending_metric_pulls(min_hours=24, max_hours=72)
        log.info("[Metrics] %d records ready for metric pull", len(pending))
        updated = 0
        for record in pending:
            platform = record["platform"]
            post_id  = record["post_id"]
            uploader = self.uploaders.get(platform)
            if not uploader or not hasattr(uploader, "get_metrics"):
                continue
            try:
                metrics = uploader.get_metrics(post_id)
                if metrics:
                    self.analytics.record_metrics(
                        post_id  = post_id,
                        platform = platform,
                        metrics  = metrics,
                        attempt  = 1,
                    )
                    updated += 1
                    log.info("[Metrics] ✓ %s %s: %s views, %s likes",
                             platform, post_id[:12],
                             metrics.get("views", 0), metrics.get("likes", 0))
            except Exception as e:
                log.warning("[Metrics] Failed %s %s: %s", platform, post_id[:12], e)
        return updated
