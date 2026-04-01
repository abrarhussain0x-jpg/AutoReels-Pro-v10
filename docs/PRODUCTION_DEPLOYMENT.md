# AutoReels Pro v10.0 — Production Deployment Guide

## Overview

**10x More Real than v9:**
- ✅ PostgreSQL database (not SQLite) for concurrency
- ✅ Redis for caching + Celery job queue
- ✅ Async/parallel processing (4 workers, scheduled tasks)
- ✅ Kubernetes-ready deployment manifests
- ✅ GitHub Actions CI/CD (test → build → deploy)
- ✅ Sentry error tracking + monitoring
- ✅ Health checks + metrics (Prometheus)
- ✅ Multi-account rotation per platform
- ✅ Dead letter queue for failed uploads
- ✅ Real-time dashboard with auto-refresh

---

## Quick Start (Local Development)

```bash
# 1. Clone and setup
git clone https://github.com/your-org/autoreels-pro.git
cd autoreels-pro
cp .env.example .env

# 2. Edit .env with your API keys
nano .env
# - ANTHROPIC_API_KEY: get from https://console.anthropic.com
# - FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN: from Facebook App
# - REDIS_URL, DATABASE_URL: will be provided by Docker

# 3. Run deployment script
bash scripts/deploy.sh

# 4. Access services
# Dashboard: http://localhost:5000
# Celery Flower: http://localhost:5555
# Database: postgresql://autoreels:...@localhost:5432/autoreels
```

---

## Docker Compose (Full Local Stack)

```bash
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web
docker-compose logs -f celery-worker

# Run migrations
docker-compose exec web python cloud/src/database/migrate.py

# Stop everything
docker-compose down -v  # -v removes volumes
```

**Services:**
- `postgres` - PostgreSQL database (port 5432)
- `redis` - Redis cache (port 6379)
- `web` - Flask dashboard (port 5000)
- `celery-worker` - Async job processor (4 workers)
- `celery-beat` - Task scheduler
- `flower` - Celery monitoring (port 5555)

---

## GitHub Actions CI/CD

### 1. Add GitHub Secrets

Go to repo → Settings → Secrets and add:

```
ANTHROPIC_API_KEY=sk-ant-v1-...
FB_PAGE_ID=123456789
FB_PAGE_ACCESS_TOKEN=eaa...
SLACK_WEBHOOK=https://hooks.slack.com/...

# For production deployment:
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
SENTRY_DSN=https://...

# For Railway.app deployment:
RAILWAY_TOKEN=...
RAILWAY_PROJECT_ID=...
RAILWAY_SERVICE_ID=...
```

### 2. Workflow Triggers

**On push to main:**
- ✅ Run pytest (tests + coverage)
- ✅ Build Docker image
- ✅ Push to GHCR (GitHub Container Registry)
- ✅ Notify Slack

**On push to production:**
- ✅ All above + Deploy to Railway.app
- ✅ Run migrations
- ✅ Notify Slack on success/failure

### 3. View CI/CD Status

```
https://github.com/your-org/autoreels-pro/actions
```

---

## Production Deployment (Railway.app)

### 1. Connect GitHub Repo

1. Go to https://railway.app
2. New Project → Deploy from GitHub
3. Select your repo
4. Configure environment variables (from GitHub Secrets)

### 2. Configure Services

**Web Service:**
```yaml
Start Command: python cloud/src/dashboard/app_v2.py
PORT: 5000
```

**Celery Worker Service:**
```yaml
Start Command: celery -A src.tasks worker -l info -c 4
```

**Celery Beat Service:**
```yaml
Start Command: celery -A src.tasks beat -l info
```

**PostgreSQL Plugin:** Add from Railway marketplace

**Redis Plugin:** Add from Railway marketplace

### 3. Deploy

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up --service YOUR_SERVICE_ID
```

---

## Kubernetes Deployment

### 1. Create Secrets

```bash
kubectl create namespace autoreels

kubectl create secret generic autoreels-secrets \
  --from-literal=database_url="postgresql://..." \
  --from-literal=redis_url="redis://..." \
  --from-literal=anthropic_api_key="sk-ant-..." \
  --from-literal=slack_webhook="https://..." \
  -n autoreels

kubectl create configmap autoreels-config \
  --from-literal=fb_page_ids="123456789,987654321" \
  -n autoreels
```

### 2. Deploy

```bash
kubectl apply -f k8s/autoreels-deployment.yaml
```

### 3. Monitor

```bash
# Check pods
kubectl get pods -n autoreels

# View logs
kubectl logs -f deployment/autoreels-pro-web -n autoreels

# Port forward
kubectl port-forward svc/autoreels-pro 5000:5000 -n autoreels
# Access: http://localhost:5000
```

---

## Database Migrations

### Create Migration

```bash
cd cloud
python -m alembic revision --autogenerate -m "description"
```

### Run Migration

```bash
# Local
python src/database/migrate.py

# Docker
docker-compose exec web python src/database/migrate.py

# Kubernetes
kubectl exec -it deployment/autoreels-pro-web -c web \
  -- python src/database/migrate.py
```

---

## Monitoring & Alerts

### Sentry (Error Tracking)

1. Create account at https://sentry.io
2. Add `SENTRY_DSN` to environment
3. Errors automatically sent + notified

### Prometheus Metrics

Access at `/metrics` endpoint:
```
curl http://localhost:5000/metrics
```

Metrics include:
- `autoreels_videos_total` — Total videos processed
- `autoreels_uploads_total` — Total platform uploads
- `autoreels_avg_views` — Average engagement

### Health Checks

```bash
# Liveness
curl http://localhost:5000/health

# Readiness
curl http://localhost:5000/ready

# Full status
curl http://localhost:5000/status
```

---

## Troubleshooting

### "Database connection failed"
```bash
# Check DATABASE_URL is set
echo $DATABASE_URL

# Test connection
psql $DATABASE_URL -c "SELECT 1"
```

### "Celery tasks not running"
```bash
# Check Redis
redis-cli ping

# Check Celery worker logs
docker-compose logs celery-worker

# Check beat schedule
docker-compose logs celery-beat
```

### "Claude API errors"
```bash
# Check ANTHROPIC_API_KEY
echo $ANTHROPIC_API_KEY | head -c 20

# Check quota/errors at https://console.anthropic.com/account/billing/overview
```

### "Dashboard won't load"
```bash
# Check Flask app
docker-compose logs web

# Test endpoint
curl http://localhost:5000/health
```

---

## Environment Variables Reference

| Variable | Required | Example |
|----------|----------|---------|
| `ENVIRONMENT` | No | `production` |
| `ANTHROPIC_API_KEY` | ✅ Yes | `sk-ant-v1-...` |
| `DATABASE_URL` | ✅ Yes (prod) | `postgresql://user:pass@host/db` |
| `REDIS_URL` | ✅ Yes | `redis://host:6379/0` |
| `FB_PAGE_IDS` | No | `123456789,987654321` |
| `FB_ACCESS_TOKENS` | No | `{"123456789":"token1"}` |
| `SLACK_WEBHOOK` | No | `https://hooks.slack.com/...` |
| `SENTRY_DSN` | No | `https://...@sentry.io/...` |
| `DRY_RUN` | No | `false` |
| `DEBUG` | No | `false` |

---

## Performance Tuning

### PostgreSQL Connection Pool
```python
# cloud/src/config.py
DB_POOL_SIZE = 20  # Increase for high load
DB_MAX_OVERFLOW = 40
```

### Celery Workers
```bash
# More workers for parallel processing
celery -A src.tasks worker -c 8 -l info

# Or in docker-compose.yml
command: celery -A src.tasks worker -l info -c 8
```

### Redis Memory
```bash
# Monitor Redis memory
redis-cli info memory

# Increase max memory in redis.conf
maxmemory 256mb
maxmemory-policy allkeys-lru
```

---

## Scaling

### Horizontal Scaling (Multiple Regions)
1. Deploy multiple instances of `web` service
2. Use load balancer (Railway/Kubernetes provides)
3. Use single PostgreSQL + Redis (cloud-managed)

### Vertical Scaling (Bigger Machines)
1. Increase machine size in Railway/Kubernetes
2. Increase `DB_POOL_SIZE`
3. Increase `celery -c` (worker concurrency)

---

## Backup & Recovery

### PostgreSQL Backup
```bash
# Local backup
pg_dump $DATABASE_URL > backup.sql

# Restore
psql $DATABASE_URL < backup.sql
```

### Redis Backup
```bash
# Enable RDB persistence in docker-compose
# Or use Railway managed Redis (auto backups)
redis-cli BGSAVE
```

---

## Support & Monitoring

**Logs:**
- GitHub Actions: https://github.com/your-org/autoreels-pro/actions
- Sentry: https://sentry.io/organizations/your-org/
- Railway: https://railway.app/project/YOUR_PROJECT
- Kubernetes: `kubectl logs -f deployment/autoreels-pro-web`

**Metrics:**
- Celery: http://localhost:5555 (Flower)
- Prometheus: http://localhost:5000/metrics
- Dashboard: http://localhost:5000/status

**Alerts:**
- Slack: Check #autoreels-alerts channel
- Email: Check inbox for Sentry notifications
- Phone: Configure PagerDuty integration in Sentry

---

**Questions?** Check GitHub Issues or reach out to your team lead.
