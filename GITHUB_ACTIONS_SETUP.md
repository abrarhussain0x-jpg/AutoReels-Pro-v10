# GitHub Actions — Complete Deployment Guide

## Step 1: Fork/Clone Repository

```bash
git clone https://github.com/your-org/autoreels-pro.git
cd autoreels-pro
git remote add origin https://github.com/your-org/autoreels-pro.git
git push -u origin main
```

---

## Step 2: Add GitHub Secrets

**Navigate to:** Repository → Settings → Secrets and Variables → Actions

### Required Secrets (Minimum)

```
ANTHROPIC_API_KEY
├─ Get from: https://console.anthropic.com/account/billing/overview
├─ Format: sk-ant-v1-...
└─ Scope: Production + Development

FB_PAGE_ID
├─ Get from: Facebook Graph API Explorer
├─ Format: Numeric ID (123456789)
└─ Scope: Production + Development

FB_PAGE_ACCESS_TOKEN
├─ Get from: Facebook Developer Dashboard → Apps → Your App → Token
├─ Format: eaa...
├─ Expires: Check expiration date
└─ Scope: Production + Development
```

### Optional (for advanced features)

```
DATABASE_URL (Production only)
├─ Format: postgresql://user:pass@host:5432/dbname
├─ Provider: Railway.app, AWS RDS, Digital Ocean, Heroku
└─ Scope: Production

REDIS_URL (Production only)
├─ Format: redis://host:6379/0
├─ Provider: Railway.app, Upstash, AWS ElastiCache
└─ Scope: Production

SENTRY_DSN (Error Tracking)
├─ Get from: https://sentry.io
├─ Format: https://key@sentry.io/project_id
└─ Scope: Production

SLACK_WEBHOOK
├─ Get from: Slack Workspace → Settings → App Workflows
├─ Format: https://hooks.slack.com/services/YOUR/WEBHOOK
└─ Scope: Production + Development

DISCORD_WEBHOOK
├─ Get from: Discord Server → Channel Settings → Integrations
├─ Format: https://discordapp.com/api/webhooks/YOUR/WEBHOOK
└─ Scope: Production

TELEGRAM_TOKEN
├─ Get from: @BotFather on Telegram
├─ Format: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
└─ Scope: Production

RAILWAY_TOKEN (for Railway.app deployment)
├─ Get from: Railway Dashboard → Account → API Tokens
├─ Format: Bearer token
└─ Scope: Production only

RAILWAY_PROJECT_ID
├─ Get from: Railway Project Settings
├─ Format: Unique ID
└─ Scope: Production only

RAILWAY_SERVICE_ID
├─ Get from: Railway Service Settings
├─ Format: Unique ID (for web service)
└─ Scope: Production only
```

---

## Step 3: Set Up Environment Variables

### Development (.env file)

```bash
cp .env.example .env
# Edit with your local/dev values
```

**Local .env:**
```
ENVIRONMENT=development
DEBUG=true
ANTHROPIC_API_KEY=sk-ant-v1-...
DATABASE_URL=postgresql://localhost/autoreels
REDIS_URL=redis://localhost:6379
FB_PAGE_ID=123456789
FB_PAGE_ACCESS_TOKEN=eaa...
SLACK_WEBHOOK=https://hooks.slack.com/...
DRY_RUN=false
```

### Production (GitHub Secrets + Railway Variables)

Railway will use GitHub Secrets automatically. Additional setup:

```bash
# In Railway Dashboard → Variables
DATABASE_URL=postgresql://... (set in Railway)
REDIS_URL=redis://... (set in Railway)
ENVIRONMENT=production
DEBUG=false
ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Step 4: Understand GitHub Actions Workflow

### `.github/workflows/deploy.yml` Explained

**Triggers:**
```yaml
on:
  push:
    branches: [main, production]  # Run on push to these branches
  pull_request:
    branches: [main]              # Run on PR to main
```

**Jobs:**

#### 1. `test` Job
- Runs on every push/PR
- Tests code in PostgreSQL container
- Runs pytest with coverage
- **Does NOT deploy**

```bash
# What runs:
pytest tests/ -v --cov=src

# Required secrets: ANTHROPIC_API_KEY, FB_PAGE_ID
```

#### 2. `build` Job
- Runs after tests pass
- Builds Docker image
- Pushes to GitHub Container Registry (GHCR)
- **Runs only on push (not PR)**

```bash
# What happens:
docker build -t ghcr.io/your-org/autoreels-pro:latest .
docker push ghcr.io/your-org/autoreels-pro:latest
```

#### 3. `deploy` Job
- **ONLY runs on push to `production` branch**
- Deploys to Railway.app
- Notifies Slack

```bash
# What happens:
railway up --service YOUR_SERVICE_ID
# Sends Slack notification
```

---

## Step 5: Create Secret Checklist

Copy this checklist into a secret Notion/Obsidian doc (not git):

```
GitHub Secrets Checklist
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REQUIRED (Development + Production):
☐ ANTHROPIC_API_KEY
  └─ Value: sk-ant-v1-...
  └─ Expires: Never
  
☐ FB_PAGE_ID
  └─ Value: 123456789
  └─ Expires: Never
  
☐ FB_PAGE_ACCESS_TOKEN
  └─ Value: eaa...
  └─ Expires: Check monthly
  └─ Refresh: https://developers.facebook.com/tools/debug/token/

OPTIONAL (Development):
☐ SLACK_WEBHOOK
☐ DISCORD_WEBHOOK

PRODUCTION ONLY:
☐ DATABASE_URL (Railway provides)
☐ REDIS_URL (Railway provides)
☐ SENTRY_DSN
☐ RAILWAY_TOKEN
☐ RAILWAY_PROJECT_ID
☐ RAILWAY_SERVICE_ID

Last Updated: 2024-03-27
Reviewed By: _______
```

---

## Step 6: First Deployment

### Local Testing (Before Git)

```bash
# 1. Install deps
pip install -r cloud/requirements.txt

# 2. Run tests locally
pytest cloud/tests/ -v

# 3. Run smoke test (dry-run)
python cloud/run_pipeline.py --dry-run

# 4. Check all secrets are valid
python cloud/src/config.py validate
```

### Push to GitHub

```bash
# Add all secrets first (see Step 2)

# Create & push branch
git add .
git commit -m "Add AutoReels Pro v10 with GitHub Actions"
git push origin main

# Monitor CI/CD
# Go to https://github.com/your-org/autoreels-pro/actions
# Watch for test job to pass
```

### Deploy to Production

```bash
# Push to production branch (triggers deploy)
git checkout -b production
git push origin production

# Monitor deployment
# Go to Railway Dashboard → Deployments
# Check logs in Railway
# Verify Slack notification received
```

---

## Step 7: Troubleshooting GitHub Actions

### Test Job Fails

```
❌ ANTHROPIC_API_KEY not found
```

**Fix:** Go to Settings → Secrets → Check ANTHROPIC_API_KEY exists

```
❌ Database connection failed
```

**Fix:** Workflow starts PostgreSQL container automatically, check if it's healthy

```
❌ Tests pass but build fails
```

**Fix:** Docker build issue. Check Dockerfile. Check logs in Actions tab.

### Deploy Job Fails

```
❌ RAILWAY_TOKEN expired
```

**Fix:** Regenerate token in Railway Dashboard

```
❌ Slack notification failed
```

**Fix:** Check SLACK_WEBHOOK is correct (copy from Slack, not memory)

---

## Step 8: Monitoring Deployments

### After Deploy

1. **Check Deployment Status**
   - Railway Dashboard: https://railway.app
   - GitHub Actions: https://github.com/your-org/autoreels-pro/actions
   - Slack: Check #autoreels-alerts channel

2. **Health Checks**
   ```bash
   curl https://autoreels-pro-YOUR-ID.railway.app/health
   # Response: {"status": "alive", ...}
   
   curl https://autoreels-pro-YOUR-ID.railway.app/ready
   # Response: {"status": "ready", "database": "connected"}
   ```

3. **View Logs**
   ```bash
   # Railway CLI
   railway logs
   
   # Or Railway Dashboard → Logs tab
   ```

4. **Monitor with Sentry**
   - https://sentry.io → Projects → autoreels-pro
   - Errors auto-reported from production

---

## Step 9: Continuous Improvement

### Weekly

- Check SENTRY_DSN for errors
- Verify Facebook token not expired (refresh at https://developers.facebook.com/tools/debug/token/)
- Review Slack alerts in #autoreels-alerts

### Monthly

- Audit GitHub Secrets (Settings → Secrets)
- Update Railway PostgreSQL/Redis (if managed by Railway)
- Test rollback procedure

### Quarterly

- Rotate tokens/secrets
- Review cost in Railway Dashboard
- Load test with `artillery` or `locust`

---

## Step 10: Advanced: Manual Deployment

If you need to deploy without committing code:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy directly
railway up --service YOUR_SERVICE_ID

# View deployment
railway logs -f
```

---

## Quick Reference

| Command | What It Does |
|---------|------------|
| `git push origin main` | Runs test + build on main (no deploy) |
| `git push origin production` | Runs test + build + **deploy to Railway** |
| `railway logs -f` | Watch live logs |
| `railway down` | Stop/pause service |
| `railway status` | Check deployment status |

---

## Secrets Expiration Dates

| Secret | Expires | How to Check | How to Refresh |
|--------|---------|-------------|---------------|
| ANTHROPIC_API_KEY | Never | Check on console.anthropic.com | N/A |
| FB_PAGE_ACCESS_TOKEN | 60 days | https://developers.facebook.com/tools/debug/token/ | Use refresh token / re-authorize |
| RAILWAY_TOKEN | Never | Check in Railway Dashboard | Revoke + create new |

---

**Next Steps:**
1. ✅ Add all secrets (Step 2)
2. ✅ Push to main (Step 6)
3. ✅ Monitor test job (Step 8)
4. ✅ Push to production (Step 6)
5. ✅ Verify health checks (Step 8)

**Having Issues?** Check GitHub Actions logs: https://github.com/your-org/autoreels-pro/actions
