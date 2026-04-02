"""Real-time monitoring dashboard and metrics endpoints."""

import time
from typing import Dict, Any, List
from datetime import datetime, timedelta
from src.health.observability import get_metrics, get_health_check


class DashboardMetrics:
    """Aggregated metrics for dashboard display."""

    def __init__(self):
        self.metrics = get_metrics()
        self.health = get_health_check()

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data."""
        metrics = self.metrics
        health_status = self.health.status()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": {
                "healthy": health_status["healthy"],
                "checks": health_status["checks"],
                "errors": health_status["errors"]
            },
            "performance": {
                "total_operations": sum(metrics.counters.values()),
                "counters": metrics.counters,
                "recent_metrics": self._get_recent_metrics()
            },
            "pipeline": {
                "videos_processed": metrics.counters.get("videos_processed", 0),
                "videos_failed": metrics.counters.get("videos_failed", 0),
                "success_rate": self._calculate_success_rate(),
                "avg_processing_time_ms": self._get_avg_processing_time()
            },
            "api": {
                "requests_total": metrics.counters.get("api_requests", 0),
                "errors": metrics.counters.get("api_errors", 0),
                "error_rate": self._calculate_error_rate()
            }
        }

    def _get_recent_metrics(self, limit: int = 10) -> List[Dict]:
        """Get recent metrics."""
        metrics_list = self.metrics.metrics[-limit:]
        return [
            {
                "name": m.name,
                "value": m.value,
                "unit": m.unit,
                "timestamp": m.timestamp
            }
            for m in metrics_list
        ]

    def _calculate_success_rate(self) -> float:
        """Calculate video processing success rate."""
        processed = self.metrics.counters.get("videos_processed", 0)
        failed = self.metrics.counters.get("videos_failed", 0)
        total = processed + failed
        
        if total == 0:
            return 0.0
        
        return (processed / total) * 100

    def _get_avg_processing_time(self) -> float:
        """Get average video processing time."""
        processing_times = [
            m.value for m in self.metrics.metrics 
            if m.name == "video_processing_time" and m.unit == "ms"
        ]
        
        if not processing_times:
            return 0.0
        
        return sum(processing_times) / len(processing_times)

    def _calculate_error_rate(self) -> float:
        """Calculate API error rate."""
        total = self.metrics.counters.get("api_requests", 0)
        errors = self.metrics.counters.get("api_errors", 0)
        
        if total == 0:
            return 0.0
        
        return (errors / total) * 100


class MetricsAPI:
    """REST API endpoints for metrics."""

    @staticmethod
    def get_metrics_endpoint() -> Dict[str, Any]:
        """GET /metrics - Return all metrics."""
        dashboard = DashboardMetrics()
        return dashboard.get_dashboard_data()

    @staticmethod
    def get_health_endpoint() -> Dict[str, Any]:
        """GET /health - Return health status."""
        health = get_health_check()
        return health.status()

    @staticmethod
    def get_performance_endpoint() -> Dict[str, Any]:
        """GET /metrics/performance - Return performance metrics."""
        metrics = get_metrics()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "performance": {
                "total_metrics": len(metrics.metrics),
                "counters": metrics.counters
            }
        }


class DashboardHTML:
    """Generate simple HTML dashboard."""

    @staticmethod
    def generate_dashboard_html() -> str:
        """Generate dashboard HTML."""
        dashboard = DashboardMetrics()
        data = dashboard.get_dashboard_data()
        
        # Determine system status class
        system_status_class = "status" if data['system']['healthy'] else "status error"
        system_status_text = "✓ Healthy" if data['system']['healthy'] else "✗ Issues"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>AutoReels Pro - Dashboard</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    background: #0f1419;
                    color: #e0e0e0;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                }}
                h1 {{
                    color: #00d9ff;
                    margin-bottom: 30px;
                }}
                .metrics {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .metric-card {{
                    background: #1e2329;
                    border: 1px solid #00d9ff;
                    border-radius: 8px;
                    padding: 20px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .metric-label {{
                    color: #999;
                    font-size: 12px;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }}
                .metric-value {{
                    font-size: 32px;
                    font-weight: bold;
                    color: #00d9ff;
                }}
                .status {{
                    color: #4ade80;
                }}
                .status.error {{
                    color: #f87171;
                }}
                .timestamp {{
                    text-align: center;
                    color: #666;
                    font-size: 12px;
                    margin-top: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎬 AutoReels Pro Dashboard</h1>
                
                <div class="metrics">
                    <div class="metric-card">
                        <div class="metric-label">Videos Processed</div>
                        <div class="metric-value">{data['pipeline']['videos_processed']}</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Success Rate</div>
                        <div class="metric-value">{data['pipeline']['success_rate']:.1f}%</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Avg Processing Time</div>
                        <div class="metric-value">{data['pipeline']['avg_processing_time_ms']:.0f}ms</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">System Status</div>
                        <div class="metric-value {system_status_class}">
                            {system_status_text}
                        </div>
                    </div>
                </div>
                
                <div class="timestamp">
                    Last updated: {data['timestamp']}
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
