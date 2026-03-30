"""AutoReels Pro v10 — Load Testing with Locust"""

from locust import HttpUser, task, between, events
import random
import json
import logging

logger = logging.getLogger(__name__)

class AutoReelsUser(HttpUser):
    """Simulated user making requests to AutoReels API"""
    
    wait_time = between(1, 5)  # Wait 1-5 seconds between requests
    
    def on_start(self):
        """Setup for each user"""
        self.api_key = "test-api-key"
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self.video_ids = []
        self.upload_ids = []
    
    @task(3)
    def health_check(self):
        """Check API health"""
        self.client.get("/health", headers=self.headers)
    
    @task(2)
    def get_status(self):
        """Get system status"""
        self.client.get("/api/status", headers=self.headers)
    
    @task(5)
    def list_uploads(self):
        """List recent uploads"""
        platform = random.choice(["facebook", "tiktok", "instagram"])
        params = {
            "platform": platform,
            "days": random.randint(1, 30)
        }
        self.client.get("/api/v1/uploads", params=params, headers=self.headers)
    
    @task(3)
    def get_analytics(self):
        """Get daily analytics"""
        days = random.randint(1, 90)
        self.client.get(f"/api/v1/analytics/daily?days={days}", headers=self.headers)
    
    @task(2)
    def list_accounts(self):
        """List social accounts"""
        self.client.get("/api/v1/accounts", headers=self.headers)
    
    @task(1)
    def process_video(self):
        """Submit video for processing"""
        payload = {
            "youtube_url": f"https://youtube.com/watch?v={random.randint(1000000, 9999999)}",
            "force_process": False
        }
        response = self.client.post(
            "/api/v1/videos",
            json=payload,
            headers=self.headers
        )
        if response.status_code == 200:
            data = response.json()
            self.video_ids.append(data.get("id"))
    
    @task(2)
    def get_video_status(self):
        """Check video processing status"""
        if self.video_ids:
            video_id = random.choice(self.video_ids)
            self.client.get(f"/api/v1/videos/{video_id}", headers=self.headers)
    
    @task(2)
    def get_video_clips(self):
        """Get clips for video"""
        if self.video_ids:
            video_id = random.choice(self.video_ids)
            self.client.get(f"/api/v1/videos/{video_id}/clips", headers=self.headers)
    
    @task(3)
    def get_upload_metrics(self):
        """Get engagement metrics for upload"""
        if self.upload_ids:
            upload_id = random.choice(self.upload_ids)
            self.client.get(f"/api/v1/uploads/{upload_id}/metrics", headers=self.headers)

class AdminUser(HttpUser):
    """Simulated admin making configuration requests"""
    
    wait_time = between(5, 10)
    
    def on_start(self):
        """Setup for admin"""
        self.admin_key = "admin-api-key"
        self.headers = {
            "X-API-Key": self.admin_key,
            "Content-Type": "application/json"
        }
    
    @task(1)
    def check_health(self):
        """Monitor system health"""
        self.client.get("/api/health", headers=self.headers)
    
    @task(1)
    def get_detailed_status(self):
        """Get detailed system status"""
        self.client.get("/api/status", headers=self.headers)

# ── EVENT LISTENERS ────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Hook fired when the load test starts"""
    logger.info("Load test starting...")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Hook fired when the load test stops"""
    logger.info("Load test stopping...")
    
    # Print summary
    print("\n" + "="*70)
    print("LOAD TEST SUMMARY")
    print("="*70)
    print(f"Total requests: {sum(r.num_requests for r in environment.stats.values())}")
    print(f"Total failures: {sum(r.num_failures for r in environment.stats.values())}")
    print(f"Average response time: {environment.stats.total.avg_response_time:.2f}ms")
    print(f"Min response time: {environment.stats.total.min_response_time:.2f}ms")
    print(f"Max response time: {environment.stats.total.max_response_time:.2f}ms")

@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, **kwargs):
    """Hook fired for each request"""
    if response.status_code >= 400:
        logger.warning(f"Failed request: {request_type} {name} - {response.status_code}")

# ── RUN INSTRUCTIONS ──────────────────────────────────────

"""
Run load tests:

1. Install Locust:
   pip install locust

2. Start the API:
   docker-compose up web

3. Run load test with CLI:
   locust -f cloud/tests/test_load.py --host=http://localhost:5000 -u 100 -r 10 -t 5m

   Options:
   -u 100       : 100 concurrent users
   -r 10        : Spawn 10 users per second
   -t 5m        : Run for 5 minutes
   --headless   : No web UI
   -f           : Load file

4. Or use web UI (default):
   locust -f cloud/tests/test_load.py --host=http://localhost:5000
   
   Then visit: http://localhost:8089

Expected Results:
- P95 response time < 500ms
- P99 response time < 1000ms
- Error rate < 1%
- Throughput > 100 req/sec

"""
