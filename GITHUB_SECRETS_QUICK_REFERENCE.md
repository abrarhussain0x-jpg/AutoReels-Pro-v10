# GitHub Secrets & Variables — QUICK SETUP CHECKLIST

## 🔴 REQUIRED (Must Have to Run)

### Step 1: Go to GitHub Repository Settings
```
https://github.com/YOUR_USERNAME/AutoReels-Pro-v10
  → Settings 
  → Secrets and variables 
  → Actions
```

### Step 2: Add These Required SECRETS

| Secret Name | Value | Where to Get |
|------------|-------|-------------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | https://console.anthropic.com/ |
| `FB_PAGE_ID` | `123456789...` | Find in Facebook page URL or https://findmyfbid.com/ |
| `FB_PAGE_ACCESS_TOKEN` | `EAA...` | https://developers.facebook.com/tools/explorer |
| `ENVIRONMENT` | `production` or `staging` | Choose one |

**To Add Each:**
1. Click **New repository secret**
2. Enter Name and Value
3. Click **Add secret**
4. Repeat for each secret

---

## 🟦 OPTIONAL (Nice to Have)

| Secret Name | Value | Purpose |
|------------|-------|---------|
| `SENTRY_DSN` | `https://...@sentry.io/...` | Error tracking |
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/...` | Pipeline notifications |
| `YT_DLP_COOKIES` | Netscape cookies.txt content | Bypass YouTube rate-limiting |
| `AWS_ACCESS_KEY_ID` | `AKIA...` | S3 backups |
| `AWS_SECRET_ACCESS_KEY` | Secret key | S3 backups |

---

## 📋 Variables (Not Encrypted)

Go to: **Settings → Secrets and variables → Variables**

| Variable | Value | Notes |
|----------|-------|-------|
| `NICHE` | `movie` | Can be: movie, anime, drama, news |
| `CLIP_LENGTH_SECONDS` | `55` | Range: 30-120 |
| `CLIPS_PER_VIDEO` | `3` | Range: 1-10 |
| `DAILY_UPLOAD_LIMIT` | `5` | Range: 1-50 |
| `PIPELINE_MODE` | `--once` | Use: `--once` for CI |
| `DRY_RUN_MODE` | `false` | Use: `true` for testing |

**To Add Each:**
1. Click **New repository variable**
2. Enter Name and Value
3. Click **Add variable**
4. Repeat for each variable

---

## ✅ Verification

After adding all secrets, verify with:

```bash
# Go to repository Actions tab
# https://github.com/YOUR_USERNAME/AutoReels-Pro-v10/actions

# You should see the secrets listed in workflow logs:
# ✓ ANTHROPIC_API_KEY found
# ✓ FB_PAGE_ID found
# ✓ FB_PAGE_ACCESS_TOKEN found
# ✓ ENVIRONMENT found
```

---

## 🚀 How to Get Each Value

### ANTHROPIC_API_KEY
```
1. Go to: https://console.anthropic.com/
2. Sign in or create account
3. Click "API Keys" 
4. Click "Create Key"
5. Copy the key (starts with "sk-ant-")
6. Paste into GitHub Secret
```

### FB_PAGE_ID
```
1. Go to your Facebook page
2. Look at URL: facebook.com/pages/PageName/[THIS_IS_YOUR_ID]
3. Copy just the number
4. Paste into GitHub Secret
```

### FB_PAGE_ACCESS_TOKEN
```
1. Go to: https://developers.facebook.com/tools/explorer
2. From dropdown, select YOUR_APP_NAME
3. Click "Generate Access Token"
4. Select your Facebook page
5. Click "Get Token"
6. Copy the long token (starts with "EAA")
7. Paste into GitHub Secret
```

### ENVIRONMENT
```
Choose ONE:
- production = Upload to real Facebook page
- staging = Upload to test page (recommended for first time)
- development = Don't upload (dry-run only, test locally)
```

---

## 🎯 Recommended Setup for First Time

**Use these values to TEST safely:**

```
ENVIRONMENT = staging
NICHE = movie
CLIP_LENGTH_SECONDS = 55
CLIPS_PER_VIDEO = 2
DAILY_UPLOAD_LIMIT = 3
PIPELINE_MODE = --once
DRY_RUN_MODE = false
```

This will:
- ✓ Process videos without uploading to real Facebook
- ✓ Test all components end-to-end
- ✓ Generate test videos in `cloud/queue/` directory
- ✓ Show what would be uploaded before going live

---

## ⚠️ Common Mistakes to AVOID

❌ **DON'T:**
- Put secrets in `.env` file or commit them
- Use the same token for multiple environments
- Share tokens in Slack/email/chat
- Forget to refresh expired tokens
- Leave `DRY_RUN_MODE = false` when testing

✅ **DO:**
- Store tokens in GitHub Secrets only
- Rotate tokens monthly
- Keep separate tokens for staging/production
- Test with `DRY_RUN_MODE = true` first
- Verify secrets are set before running workflow

---

## 🔄 What Happens After Setup

1. **GitHub Actions Workflow triggers** (daily or on manual trigger)
2. **Workflow reads all Secrets & Variables**
3. **Pipeline runs with your settings**
4. **Videos get processed and uploaded** (based on ENVIRONMENT)
5. **Logs show in Actions tab** with all details

---

## 📞 If Something Goes Wrong

**Check these in order:**

1. Go to: **Settings → Secrets and variables → Actions**
   - Verify all 4 REQUIRED secrets are present
   - Check spelling exactly: `ANTHROPIC_API_KEY` (not `API_KEY` or `ANTHROPIC_KEY`)

2. Go to: **Actions tab → Latest workflow run**
   - Expand logs to see which step failed
   - Look for error message starting with "✓" (pass) or "✗" (fail)

3. Read: **GITHUB_ACTIONS_TROUBLESHOOTING.md**
   - Has solutions for common errors

---

## 📊 At a Glance

| Item | Required? | Where to Paste | Type |
|------|-----------|----------------|------|
| ANTHROPIC_API_KEY | ✅ YES | **Secrets** | Secret |
| FB_PAGE_ID | ✅ YES | **Secrets** | Secret |
| FB_PAGE_ACCESS_TOKEN | ✅ YES | **Secrets** | Secret |
| ENVIRONMENT | ✅ YES | **Secrets** | Secret |
| SENTRY_DSN | ⭕ NO | **Secrets** | Secret |
| SLACK_WEBHOOK_URL | ⭕ NO | **Secrets** | Secret |
| YT_DLP_COOKIES | ⭕ NO | **Secrets** | Secret |
| NICHE | ✅ YES | **Variables** | Variable |
| CLIP_LENGTH_SECONDS | ✅ YES | **Variables** | Variable |
| CLIPS_PER_VIDEO | ✅ YES | **Variables** | Variable |
| DAILY_UPLOAD_LIMIT | ✅ YES | **Variables** | Variable |
| PIPELINE_MODE | ✅ YES | **Variables** | Variable |
| DRY_RUN_MODE | ✅ YES | **Variables** | Variable |

---

## 🎓 Learning Resources

- **GitHub Secrets Docs:** https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions
- **Anthropic API:** https://console.anthropic.com/docs
- **Facebook Graph API:** https://developers.facebook.com/docs/graph-api
- **AutoReels Docs:** See README.md

---

**Last Updated:** April 1, 2026  
**For:** AutoReels Pro v10.0
