# GitHub Secrets & Variables Setup Guide

## Overview

AutoReels-Pro-v10 requires specific GitHub Secrets and Environment Variables to function properly in CI/CD. This guide walks through all required and optional settings.

---

## 🔐 REQUIRED GitHub Secrets

These must be set in: **Settings → Secrets and variables → Actions**

### 1. **ANTHROPIC_API_KEY** (REQUIRED)
**Purpose:** OpenAI-compatible API key for content generation  
**Where to Get:**
- Go to https://console.anthropic.com/
- Create/copy your API key
- Ensure you have sufficient credits

**How to Add:**
1. Go to repository → **Settings**
2. Click **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `ANTHROPIC_API_KEY`
5. Value: `sk-ant-...` (your actual key)
6. Click **Add secret**

**Test:**
```bash
python cloud/check_env.py
# Should output: ✓ ANTHROPIC_API_KEY found
```

---

### 2. **FB_PAGE_ID** (REQUIRED for Facebook uploads)
**Purpose:** Facebook Page ID for automated posting  
**Where to Get:**
- Go to https://facebook.com/yourpage
- Look at URL: `facebook.com/pages/PageName/PAGE_ID`
- Or use: https://findmyfbid.com/

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `FB_PAGE_ID`
4. Value: `123456789012345` (numeric ID only)
5. Click **Add secret**

**Example Values:**
```
FB_PAGE_ID = 123456789012345  ← 15-digit number
```

---

### 3. **FB_PAGE_ACCESS_TOKEN** (REQUIRED for Facebook uploads)
**Purpose:** Facebook Graph API token for posting permissions  
**Where to Get:**
1. Go to https://developers.facebook.com/
2. Create an app (if not already created)
3. Go to **Settings** → **Basic** → Copy **App ID** and **App Secret**
4. Go to **Tools** → **Graph API Explorer**
5. Select your app from dropdown
6. Click **Get Token** → **Page Access Token**
7. Select your page
8. Copy the generated token

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `FB_PAGE_ACCESS_TOKEN`
4. Value: `EAA...` (very long token starting with EAA)
5. Click **Add secret**

**Example Values:**
```
FB_PAGE_ACCESS_TOKEN = EAABsbCS1iHgBAO...  ← ~200+ character token
```

**Token Expiration:**
- Short-lived tokens: 1-2 hours
- Long-lived tokens: ~60 days
- **Action:** Refresh token monthly or implement auto-refresh (see Token Refresher)

---

### 4. **ENVIRONMENT** (REQUIRED)
**Purpose:** Deployment environment identifier  
**Valid Values:**
- `production` - Live uploads to Facebook
- `staging` - Test uploads with validation
- `development` - Local dry-run testing

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `ENVIRONMENT`
4. Value: `production` or `staging` or `development`
5. Click **Add secret**

**Recommended for CI:**
```
ENVIRONMENT = staging  ← Use staging for initial testing
```

---

## 🟦 Optional GitHub Secrets

### 5. **SENTRY_DSN** (OPTIONAL - Error Tracking)
**Purpose:** Send errors to Sentry for monitoring  
**Where to Get:**
- Sign up at https://sentry.io/ (free tier available)
- Create project for Python
- Copy DSN from **Settings** → **Client Keys (DSN)**

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Name: `SENTRY_DSN`
3. Value: `https://...@sentry.io/...`

**Use Case:** Monitor production errors without needing logs

---

### 6. **SLACK_WEBHOOK_URL** (OPTIONAL - Notifications)
**Purpose:** Send pipeline notifications to Slack  
**Where to Get:**
1. Go to your Slack workspace
2. Create incoming webhook: https://api.slack.com/messaging/webhooks
3. Copy webhook URL

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Name: `SLACK_WEBHOOK_URL`
3. Value: `https://hooks.slack.com/services/...`

**Use Case:** Get alerts when pipeline succeeds/fails

---

### 7. **YT_DLP_COOKIES** (OPTIONAL - YouTube Auth)
**Purpose:** Authenticated YouTube access to bypass rate-limiting  
**Where to Get:**
1. Install browser extension: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-custom-headers-to-yt-dlp
2. Get cookies from YouTube in Netscape format
3. Save to `cookies.txt`

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Name: `YT_DLP_COOKIES`
3. Value: (multiline - paste entire cookies.txt content)
4. Make sure to use **multiline secret** handling

**Use Case:** Bypass YouTube rate-limiting for high-volume downloads

---

### 8. **AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY** (OPTIONAL - S3 Backups)
**Purpose:** Backup database and videos to AWS S3  
**Where to Get:**
1. Go to https://console.aws.amazon.com/
2. Create IAM user with S3 access
3. Generate access key and secret key

**How to Add:**
1. Repository → **Settings** → **Secrets and variables** → **Actions**
2. Add two secrets:
   - Name: `AWS_ACCESS_KEY_ID`, Value: `AKIA...`
   - Name: `AWS_SECRET_ACCESS_KEY`, Value: `wJa...`

**Use Case:** Automated daily database backups

---

## 📋 Repository Variables (Not Encrypted)

These go in: **Settings → Secrets and variables → Variables** (not Secrets)

### 1. **NICHE**
**Purpose:** Content niche for pipeline  
**Valid Values:** `movie`, `anime`, `drama`, `news`, etc.  
**Default:** `movie`

```bash
NICHE = movie
```

---

### 2. **CLIP_LENGTH_SECONDS**
**Purpose:** Duration of each exported clip  
**Valid Range:** `30-120`  
**Default:** `55`

```bash
CLIP_LENGTH_SECONDS = 55
```

---

### 3. **CLIPS_PER_VIDEO**
**Purpose:** Number of clips to extract per video  
**Valid Range:** `1-10`  
**Default:** `3`

```bash
CLIPS_PER_VIDEO = 3
```

---

### 4. **DAILY_UPLOAD_LIMIT**
**Purpose:** Maximum clips to upload per day  
**Valid Range:** `1-50`  
**Default:** `5`

```bash
DAILY_UPLOAD_LIMIT = 5
```

---

### 5. **PIPELINE_MODE**
**Purpose:** How often pipeline runs  
**Valid Values:**
- `--once` - Single run in CI
- `--daemon` - Continuous loop (not recommended for CI)

**Default:** `--once`

```bash
PIPELINE_MODE = --once
```

---

### 6. **DRY_RUN_MODE**
**Purpose:** Test pipeline without actual uploads  
**Valid Values:** `true`, `false`  
**Default:** `false`

```bash
DRY_RUN_MODE = false
```

---

## ✅ Setup Checklist

### Step 1: Prepare Credentials
- [ ] Have Anthropic API key ready
- [ ] Have Facebook Page ID
- [ ] Have Facebook Page Access Token (or plan to get it)
- [ ] Decide on ENVIRONMENT (production/staging/development)

### Step 2: Add Required Secrets
- [ ] Go to repository **Settings**
- [ ] Click **Secrets and variables** → **Actions**
- [ ] Add `ANTHROPIC_API_KEY`
- [ ] Add `FB_PAGE_ID`
- [ ] Add `FB_PAGE_ACCESS_TOKEN`
- [ ] Add `ENVIRONMENT`

### Step 3: Review Secrets
```bash
# In GitHub:
1. Go to Settings → Secrets and variables → Actions
2. Verify all 4 required secrets are listed:
   ✓ ANTHROPIC_API_KEY
   ✓ FB_PAGE_ID
   ✓ FB_PAGE_ACCESS_TOKEN
   ✓ ENVIRONMENT
```

### Step 4: Add Optional Secrets (if desired)
- [ ] Add `SENTRY_DSN` (if using error tracking)
- [ ] Add `SLACK_WEBHOOK_URL` (if using notifications)
- [ ] Add `YT_DLP_COOKIES` (if using YouTube auth)
- [ ] Add `AWS_ACCESS_KEY_ID` & `AWS_SECRET_ACCESS_KEY` (if using backups)

### Step 5: Add Variables (Not Encrypted)
- [ ] Go to **Variables** (same location as Secrets)
- [ ] Add `NICHE` = `movie`
- [ ] Add `CLIP_LENGTH_SECONDS` = `55`
- [ ] Add `CLIPS_PER_VIDEO` = `3`
- [ ] Add `DAILY_UPLOAD_LIMIT` = `5`
- [ ] Add `PIPELINE_MODE` = `--once`
- [ ] Add `DRY_RUN_MODE` = `false`

### Step 6: Test Configuration
```bash
# Verify secrets are loaded correctly
cd cloud
python check_env.py

# Should output:
# ✓ ANTHROPIC_API_KEY found
# ✓ FB_PAGE_ID found
# ✓ FB_PAGE_ACCESS_TOKEN found
# ✓ ENVIRONMENT found (value: production/staging/development)
# ✓ Node.js version: v20.x
# ✓ yt-dlp version: >=2025.1.0
# ✓ FFmpeg version: >=4.0
```

---

## 🔄 How to Access Secrets in Code

### In Python Scripts:
```python
import os

# Access secrets as environment variables
anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
fb_page_id = os.environ.get("FB_PAGE_ID")
fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
environment = os.environ.get("ENVIRONMENT")

# Access variables
niche = os.environ.get("NICHE", "movie")
clip_length = int(os.environ.get("CLIP_LENGTH_SECONDS", 55))
```

### In GitHub Actions Workflow:
```yaml
jobs:
  pipeline:
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      FB_PAGE_ID: ${{ secrets.FB_PAGE_ID }}
      FB_PAGE_ACCESS_TOKEN: ${{ secrets.FB_PAGE_ACCESS_TOKEN }}
      ENVIRONMENT: ${{ secrets.ENVIRONMENT }}
      NICHE: ${{ vars.NICHE }}
```

---

## 🚨 Security Best Practices

### ✅ DO:
- ✓ Use long, random tokens
- ✓ Rotate tokens monthly
- ✓ Use separate tokens for staging/production
- ✓ Limit token permissions to minimum required
- ✓ Store in GitHub Secrets (never in code)
- ✓ Review Secret access logs regularly

### ❌ DON'T:
- ✗ Commit secrets to Git
- ✗ Log or print secrets
- ✗ Share tokens in Slack/email
- ✗ Reuse tokens across environments
- ✗ Use tokens older than 90 days
- ✗ Grant unnecessary permissions

---

## 🔑 Token Expiration & Rotation

### Facebook Access Token
- **Expiration:** ~60 days (long-lived)
- **Rotation Schedule:** Monthly
- **How to Refresh:**
  1. Go to https://developers.facebook.com/tools/explorer
  2. Select your app and page
  3. Click **Get New Access Token**
  4. Copy new token
  5. Update `FB_PAGE_ACCESS_TOKEN` secret in GitHub

### Anthropic API Key
- **Expiration:** No expiration (unless manually revoked)
- **Rotation Schedule:** Annually or if compromised
- **How to Refresh:**
  1. Go to https://console.anthropic.com/account/keys
  2. Create new API key
  3. Update `ANTHROPIC_API_KEY` secret in GitHub
  4. Delete old key once verified working

---

## 📝 Environment Configuration Examples

### Example 1: Production Setup
```
ENVIRONMENT = production
ANTHROPIC_API_KEY = sk-ant-...
FB_PAGE_ID = 123456789012345
FB_PAGE_ACCESS_TOKEN = EAA...
NICHE = movie
CLIPS_PER_VIDEO = 5
DAILY_UPLOAD_LIMIT = 10
PIPELINE_MODE = --once
DRY_RUN_MODE = false
```

### Example 2: Staging Setup (Testing)
```
ENVIRONMENT = staging
ANTHROPIC_API_KEY = sk-ant-...
FB_PAGE_ID = 123456789012345 (test page)
FB_PAGE_ACCESS_TOKEN = EAA... (test token)
NICHE = movie
CLIPS_PER_VIDEO = 2
DAILY_UPLOAD_LIMIT = 3
PIPELINE_MODE = --once
DRY_RUN_MODE = false
```

### Example 3: Development Setup (Local)
```
ENVIRONMENT = development
ANTHROPIC_API_KEY = sk-ant-...
FB_PAGE_ID = (optional)
FB_PAGE_ACCESS_TOKEN = (optional)
NICHE = movie
CLIPS_PER_VIDEO = 1
DAILY_UPLOAD_LIMIT = 1
PIPELINE_MODE = --once
DRY_RUN_MODE = true
```

---

## 🧪 Verification Commands

### Check All Secrets are Set:
```bash
# In GitHub Actions workflow logs
- name: Verify Secrets
  run: |
    [ -n "$ANTHROPIC_API_KEY" ] && echo "✓ ANTHROPIC_API_KEY set" || echo "✗ ANTHROPIC_API_KEY missing"
    [ -n "$FB_PAGE_ID" ] && echo "✓ FB_PAGE_ID set" || echo "✗ FB_PAGE_ID missing"
    [ -n "$FB_PAGE_ACCESS_TOKEN" ] && echo "✓ FB_PAGE_ACCESS_TOKEN set" || echo "✗ FB_PAGE_ACCESS_TOKEN missing"
    [ -n "$ENVIRONMENT" ] && echo "✓ ENVIRONMENT set" || echo "✗ ENVIRONMENT missing"
```

### Test Pipeline Locally:
```bash
cd cloud

# Set secrets locally (don't commit these!)
export ANTHROPIC_API_KEY="sk-ant-..."
export FB_PAGE_ID="123456789012345"
export FB_PAGE_ACCESS_TOKEN="EAA..."
export ENVIRONMENT="development"

# Test with dry-run
MODE="--once" python main.py --dry-run

# Check logs
tail -f logs/*.log
```

---

## 🆘 Troubleshooting

### Problem: "ANTHROPIC_API_KEY not found"
**Solution:**
1. Go to repository **Settings** → **Secrets and variables** → **Actions**
2. Verify `ANTHROPIC_API_KEY` is listed
3. Verify the secret value is correct (starts with `sk-ant-`)
4. If not set, click **New repository secret** and add it

### Problem: "FB_PAGE_ACCESS_TOKEN expired"
**Solution:**
1. Go to https://developers.facebook.com/tools/explorer
2. Generate new token (step 6 in FB_PAGE_ACCESS_TOKEN section)
3. Update the secret in GitHub
4. Redeploy pipeline

### Problem: "Permission denied for Facebook Page"
**Solution:**
1. Verify `FB_PAGE_ID` is correct (numeric ID only, no special chars)
2. Verify token has `pages_manage_posts` permission
3. Verify token is from correct app/page combination
4. Test token: `curl -X GET "https://graph.facebook.com/me?access_token=TOKEN"`

### Problem: "Workflow says 'GitHub Actions not found'"
**Solution:**
1. Ensure repository is **Public** or you have **Actions** enabled
2. Go to **Settings** → **Actions** → **General**
3. Select **Allow all actions and reusable workflows**
4. Save and retry

---

## 📞 Support

For GitHub Secrets issues:
- GitHub Docs: https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions
- Anthropic API: https://console.anthropic.com/docs
- Facebook Graph API: https://developers.facebook.com/docs/graph-api

For AutoReels issues:
- Check **GITHUB_ACTIONS_TROUBLESHOOTING.md**
- Review workflow logs: https://github.com/YOUR_REPO/actions
- Contact: See README.md

---

**Last Updated:** April 1, 2026  
**Version:** AutoReels Pro v10.0
