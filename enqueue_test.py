from pathlib import Path
import os, sys

# Ensure cloud is on sys.path so we can import src packages
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "cloud"))

from src.scheduler.job_queue import JobQueue

VIDEO_ID = os.environ.get("TEST_VIDEO_ID", "dQw4w9WgXcQ")
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"

q = JobQueue(Path("cloud/queue/jobs.db"))
q.enqueue(VIDEO_ID, "Test enqueue", VIDEO_URL, "TestChannel", score=0.5)
print(q.queue_report())
from pathlib import Path
from src.scheduler.job_queue import JobQueue
import os

VIDEO_ID = os.environ.get("TEST_VIDEO_ID", "dQw4w9WgXcQ")
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"

q = JobQueue(Path("cloud/queue/jobs.db"))
q.enqueue(VIDEO_ID, "Test enqueue", VIDEO_URL, "TestChannel", score=0.5)
print(q.queue_report())
