"""Comprehensive test fixtures, A/B testing framework, and load testing utilities."""

import pytest
import logging
import time
import random
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class TestData:
    """Test data fixture."""
    video_id: str = "test_video_123"
    title: str = "Test Video Title"
    description: str = "Test description"
    duration: int = 600
    view_count: int = 1000
    like_count: int = 100
    channel: str = "Test Channel"


@pytest.fixture
def test_video_data():
    """Fixture: Test video metadata."""
    return TestData()


@pytest.fixture
def mock_db(tmp_path):
    """Fixture: Mock SQLite database."""
    import sqlite3
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE videos (
            id TEXT PRIMARY KEY,
            title TEXT,
            status TEXT,
            created_at TIMESTAMP
        )
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_api_client():
    """Fixture: Mock API client."""
    class MockClient:
        def __init__(self):
            self.requests = []
        
        def get(self, url: str, **kwargs) -> Dict:
            self.requests.append(("GET", url, kwargs))
            return {"status": 200, "data": {}}
        
        def post(self, url: str, data: Dict, **kwargs) -> Dict:
            self.requests.append(("POST", url, data, kwargs))
            return {"status": 201, "data": {"id": "test_123"}}
    
    return MockClient()


# ── A/B Testing Framework ──

@dataclass
class Variant:
    """A/B test variant."""
    name: str
    weight: float  # 0.0-1.0, sum of all variants should be 1.0
    handler: Callable


class ABTestEngine:
    """
    A/B testing engine for caption variations, posting times, etc.
    
    Supports weighted random selection and statistical analysis.
    """

    def __init__(self, test_name: str, variants: List[Variant]):
        """
        Initialize A/B test.
        
        Args:
            test_name: Name of the test
            variants: List of Variant objects
        """
        self.test_name = test_name
        self.variants = variants
        self.results: Dict[str, List[float]] = {v.name: [] for v in variants}
        self.selections: Dict[str, int] = {v.name: 0 for v in variants}
        
        # Validate weights
        total_weight = sum(v.weight for v in variants)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Variant weights must sum to ~1.0, got {total_weight}")

    def select_variant(self) -> Variant:
        """Randomly select variant based on weights."""
        rand = random.random()
        cumulative = 0.0
        
        for variant in self.variants:
            cumulative += variant.weight
            if rand < cumulative:
                self.selections[variant.name] += 1
                return variant
        
        return self.variants[-1]  # Fallback to last

    def execute(self, *args, **kwargs) -> tuple[str, Any]:
        """
        Execute test: select variant and call handler.
        
        Returns:
            (variant_name, result)
        """
        variant = self.select_variant()
        result = variant.handler(*args, **kwargs)
        return variant.name, result

    def record_metric(self, variant_name: str, metric_value: float):
        """Record metric for variant."""
        if variant_name in self.results:
            self.results[variant_name].append(metric_value)

    def get_winner(self, metric: str = "mean") -> Optional[str]:
        """Determine winning variant based on metric."""
        if metric == "mean":
            avg_by_variant = {
                name: sum(values) / len(values) if values else 0
                for name, values in self.results.items()
            }
            return max(avg_by_variant, key=avg_by_variant.get) if avg_by_variant else None
        
        return None

    def get_stats(self) -> Dict[str, Dict]:
        """Get statistical summary."""
        stats = {}
        for variant_name, values in self.results.items():
            if values:
                stats[variant_name] = {
                    "count": len(values),
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "selections": self.selections[variant_name]
                }
        return stats


# ── Load Testing ──

@dataclass
class LoadTestConfig:
    """Load test configuration."""
    num_users: int = 10
    ramp_up_time: int = 10  # seconds
    duration: int = 60  # seconds
    think_time: float = 1.0  # seconds between requests per user


class LoadTester:
    """Simple load testing utility."""

    def __init__(self, config: LoadTestConfig):
        self.config = config
        self.results: List[Dict] = []
        self.errors: List[str] = []

    def run(self, request_func: Callable) -> Dict[str, Any]:
        """
        Run load test.
        
        Args:
            request_func: Async function that performs one request
            
        Returns:
            Load test results
        """
        import asyncio
        import time as time_module
        
        async def user_task(user_id: int):
            """Simulate one user making requests."""
            start_time = time_module.time()
            end_time = start_time + self.config.duration
            request_count = 0
            
            while time_module.time() < end_time:
                try:
                    req_start = time_module.time()
                    await request_func(user_id)
                    req_end = time_module.time()
                    
                    self.results.append({
                        "user_id": user_id,
                        "response_time_ms": (req_end - req_start) * 1000,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    request_count += 1
                except Exception as e:
                    self.errors.append(f"User {user_id}: {str(e)}")
                
                await asyncio.sleep(self.config.think_time)
            
            return request_count

        # Run load test
        loop = asyncio.new_event_loop()
        try:
            tasks = [
                user_task((i * self.config.ramp_up_time) // self.config.num_users)
                for i in range(self.config.num_users)
            ]
            loop.run_until_complete(asyncio.gather(*tasks))
        finally:
            loop.close()

        return self._analyze_results()

    def _analyze_results(self) -> Dict[str, Any]:
        """Analyze load test results."""
        if not self.results:
            return {"error": "No results collected"}
        
        response_times = [r["response_time_ms"] for r in self.results]
        
        return {
            "total_requests": len(self.results),
            "total_errors": len(self.errors),
            "error_rate": len(self.errors) / (len(self.results) + len(self.errors)) if (len(self.results) + len(self.errors)) > 0 else 0,
            "response_time_stats": {
                "min": min(response_times),
                "max": max(response_times),
                "mean": sum(response_times) / len(response_times),
                "median": sorted(response_times)[len(response_times) // 2],
                "p95": sorted(response_times)[int(len(response_times) * 0.95)] if response_times else 0,
                "p99": sorted(response_times)[int(len(response_times) * 0.99)] if response_times else 0,
            }
        }
