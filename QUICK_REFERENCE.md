# AutoReels Pro v10 — Quick Reference Guide

## 🎯 New Features Overview

### Phase 1: Enhanced Deployment (Done)
- ✅ PostgreSQL database (not SQLite)
- ✅ Redis for caching
- ✅ GitHub Actions CI/CD
- ✅ Kubernetes deployment manifests
- ✅ Railway.app deployment ready
- ✅ Health check endpoints
- ✅ Docker Compose with all services

### Phase 2: Advanced APIs & Testing (Done)
- ✅ FastAPI endpoints with OpenAPI docs
- ✅ REST API for video processing
- ✅ Webhooks for platform callbacks
- ✅ Rate limiting & security middleware
- ✅ Request signing & audit logging
- ✅ Pytest test framework
- ✅ Load testing with Locust
- ✅ Unit tests for database models

### Phase 3: Backup & Monitoring (Done)
- ✅ Backup/restore scripts
- ✅ S3 sync for backups
- ✅ Health check system
- ✅ Sentry integration
- ✅ Prometheus metrics endpoint
- ✅ Celery monitoring (Flower)
- ✅ Production deployment guide

---

## 🚀 Quick Start Commands

```bash
# 1. Setup
cp .env.example .env
# Edit .env with your keys

# 2. Deploy locally
bash scripts/deploy.sh

# 3. Run tests
cd cloud
pytest tests/ -v

# 4. Load test
locust -f tests/test_load.py --host=http://localhost:5000

# 5. Backup
bash scripts/backup.sh backup

# 6. Check health
curl http://localhost:5000/health
```

---

## 🔌 API Endpoints

### Health & Status
```
GET  /health                    Liveness check
GET  /api/ready                 Readiness check
GET  /api/status                System status
GET  /api/health                Detailed health
GET  /metrics                   Prometheus metrics
```

### Videos
```
POST /api/v1/videos             Submit video for processing
GET  /api/v1/videos/{id}        Get video status
GET  /api/v1/videos/{id}/clips  Get all clips for video
```

### Uploads
```
GET  /api/v1/uploads            List uploads
GET  /api/v1/uploads/{id}/metrics  Get engagement metrics
```

### Analytics
```
GET  /api/v1/analytics/daily    Daily summary
```

### Accounts
```
GET  /api/v1/accounts           List social accounts
```

### Webhooks
```
POST /webhooks/facebook         Facebook callback
POST /webhooks/instagram        Instagram callback
```

---

## 📊 Database Schema

### Core Tables
- `videos` - Source videos (11 columns, indexed on youtube_id & status)
- `clips` - Extracted clips (scene, motion, audio scores)
- `uploads` - Platform uploads (per clip, per platform)
- `post_metrics` - Engagement at time points (views/hour curve)
- `hooks` - Phrase library with UCB1 learning
- `comments` - Top comments with sentiment
- `accounts` - Social account config & auth
- `failed_jobs` - Dead letter queue
- `schedules` - Optimal posting times per niche
- `clip_scores` - ML engagement predictions

### Indexes
- Composite on (video_id, status, upload_timestamp)
- Composite on (upload_id, hours_since_upload)
- Composite on (platform, posted_at)

---

## 🔧 Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/autoreels

# Cache
REDIS_URL=redis://localhost:6379/0

# AI
ANTHROPIC_API_KEY=sk-ant-v1-...

# Platforms (space-separated or JSON)
FB_PAGE_IDS=123456789,987654321
TIKTOK_ACCESS_TOKEN=...

# Monitoring
SENTRY_DSN=https://...@sentry.io/...
SLACK_WEBHOOK=https://hooks.slack.com/...

# Control
ENVIRONMENT=production
DEBUG=false
DRY_RUN=false
```

### Feature Flags
```bash
FORCE_RUN=true          # Bypass upload window checks
DRY_RUN=true            # Full pipeline without uploads
DEBUG=true              # Verbose logging
NO_WEB=true             # Disable dashboard
```

---

## 🧪 Testing

### Run all tests
```bash
pytest tests/ -v
```

### Run only unit tests
```bash
pytest tests/test_database.py -v -m "not integration and not slow"
```

### Run with coverage
```bash
pytest tests/ --cov=cloud/src --cov-report=html
# View report: open htmlcov/index.html
```

### Run load test
```bash
# CLI mode (no UI)
locust -f tests/test_load.py --host=http://localhost:5000 -u 100 -r 10 -t 5m --headless

# Web UI
locust -f tests/test_load.py --host=http://localhost:5000
# Visit: http://localhost:8089
```

---

## 📈 Monitoring

### Metrics Endpoint
```bash
curl http://localhost:5000/metrics
```

Metrics include:
- `autoreels_videos_total` - Videos processed
- `autoreels_uploads_total` - Platform uploads
- `autoreels_avg_views` - Average engagement

### Celery Monitoring
Access at: `http://localhost:5555` (Flower)

Shows:
- Active tasks
- Worker status
- Task history
- Queue depth

### Sentry Error Tracking
1. Create account at https://sentry.io
2. Add `SENTRY_DSN` to .env
3. Errors automatically reported with context

---

## 🔐 Security Features

### Rate Limiting
- 100 req/min for anonymous users
- 10k req/min for API key holders
- Header: `X-RateLimit-Remaining`

### Security Headers
- Content-Security-Policy
- X-Content-Type-Options: nosniff
- Strict-Transport-Security
- X-XSS-Protection

### Input Validation
- URL validation (no directory traversal)
- Text sanitization (no injection)
- Filename sanitization

### Audit Logging
- All actions logged to audit_log table
- User ID, resource, action, timestamp
- Success/failure tracking

### Request Signing
- HMAC-SHA256 signatures for webhooks
- Verify with RequestSigner class
- Protects against spoofed requests

---

## 📦 Backup & Recovery

### Full backup
```bash
bash scripts/backup.sh backup
# Backups DB + Redis + App data + S3 sync
```

### Restore database
```bash
bash scripts/backup.sh restore-db backups/db_20240327_120000.sql.gz
```

### Verify backups
```bash
bash scripts/backup.sh verify
```

### Health check
```bash
bash scripts/backup.sh health
```

---

## 🚢 Deployment

### Local (Docker Compose)
```bash
docker-compose up -d
# All 7 services start: web, worker, beat, flower, postgres, redis, etc
```

### Railway.app (1-click)
```bash
# Connect GitHub repo → auto-deploy on push
# Services: PostgreSQL, Redis, web, worker, beat (managed)
```

### Kubernetes
```bash
kubectl apply -f k8s/autoreels-deployment.yaml
# Includes: Deployment, StatefulSet, Service, ConfigMap, Secrets
```

### Traditional VPS
```bash
bash scripts/deploy.sh
# Installs deps, sets up services, runs health checks
```

---

## 🐛 Troubleshooting

### "Database connection failed"
```bash
# Check DATABASE_URL
echo $DATABASE_URL

# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Migrate schema
docker-compose exec web python cloud/src/database/schema.py
```

### "Celery tasks not running"
```bash
# Check Redis
redis-cli ping

# Check worker
docker-compose logs celery-worker

# Check scheduler
docker-compose logs celery-beat

# Restart workers
docker-compose restart celery-worker celery-beat
```

### "API timeouts"
```bash
# Check worker count
curl http://localhost:5000/status | jq .celery_workers

# Increase workers
docker-compose up -d celery-worker celery-worker celery-worker

# Or in compose: scale celery-worker=4
```

### "Out of memory"
```bash
# Check container usage
docker stats

# Increase limits in docker-compose.yml
# Or deploy to bigger machine

# Clean old data
docker system prune -a
```

---

## 📚 Documentation Files

- `README.md` - Project overview
- `CHECKLIST.md` - Setup checklist
- `DEPLOY.md` - Basic deployment
- `PRODUCTION_DEPLOYMENT.md` - **READ THIS** (300+ lines)
- `.github/workflows/deploy.yml` - CI/CD workflow
- `cloud/tests/conftest.py` - Test fixtures
- `cloud/tests/test_database.py` - DB tests
- `cloud/tests/test_load.py` - Load testing

---

## 🔗 Important Links

- **Dashboard** - http://localhost:5000
- **Celery Monitor** - http://localhost:5555
- **API Docs** - http://localhost:8000/docs (FastAPI)
- **GitHub Actions** - https://github.com/your-org/autoreels-pro/actions
- **Sentry** - https://sentry.io/organizations/your-org/
- **Railway** - https://railway.app/project/YOUR_PROJECT

---

## 📞 Support

- Issues: GitHub Issues
- Docs: PRODUCTION_DEPLOYMENT.md
- Logs: `docker-compose logs -f <service>`
- Health: `curl http://localhost:5000/health`
- Backup: `bash scripts/backup.sh verify`

---

**Last Updated:** 2024-03-27  
**Version:** 10.0.0  
**Status:** Production Ready ✅
