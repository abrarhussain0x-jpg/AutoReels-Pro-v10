# GitHub Actions CI/CD Troubleshooting Guide

## Current Status ✅

**Recent Fixes Applied (April 1, 2026):**
- ✅ Updated `actions/setup-node@v3` → `v4` for Node.js 24 compatibility
- ✅ Updated Node.js version from `18` → `20`
- ✅ Enhanced yt-dlp health check with better error diagnostics
- ✅ Added environment variable validation step before pipeline runs
- ✅ Improved error handling and logging across all workflows

---

## GitHub Actions Configuration

### 1. Required Secrets

Configure these secrets in your GitHub repository settings:

**Settings → Secrets and variables → Actions**

#### Critical Secrets (Block Pipeline if Missing)
```
ANTHROPIC_API_KEY     = sk-ant-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FB_PAGE_ID            = 123456789012345
FB_PAGE_ACCESS_TOKEN  = EAABaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ENVIRONMENT           = github_actions
```

#### Optional Secrets (Used for Uploads)
```
TIKTOK_ACCESS_TOKEN        = (optional)
IG_USER_ID                = (optional)
IG_ACCESS_TOKEN           = (optional)
YOUTUBE_CLIENT_ID         = (optional)
YOUTUBE_CLIENT_SECRET     = (optional)
YOUTUBE_REFRESH_TOKEN     = (optional)
TELEGRAM_TOKEN            = (optional)
TELEGRAM_CHAT_ID          = (optional)
SLACK_WEBHOOK             = (optional)
DISCORD_WEBHOOK           = (optional)
YT_COOKIES_JSON           = (optional, for authenticated YouTube access)
```

#### Video Source Secrets
```
YOUTUBE_SOURCE_CHANNEL = https://www.youtube.com/c/CHANNEL_NAME or @HANDLE
```

### 2. Setting Up Secrets via GitHub CLI

```bash
# Authenticate
gh auth login

# Set a secret
gh secret set ANTHROPIC_API_KEY --body "sk-ant-v1-xxxxx"
gh secret set FB_PAGE_ID --body "123456789"
gh secret set FB_PAGE_ACCESS_TOKEN --body "EAABa..."
gh secret set ENVIRONMENT --body "github_actions"

# Verify
gh secret list
```

### 3. Setting Up Secrets via Web UI

1. Go to: https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10/settings/secrets/actions
2. Click "New repository secret"
3. Enter Name: `ANTHROPIC_API_KEY`
4. Enter Value: Your actual API key
5. Click "Add secret"
6. Repeat for other secrets

---

## Common Failure Scenarios & Solutions

### ❌ Error: "FB_PAGE_ID not set"

**Cause:** Required secret not configured in GitHub

**Fix:**
```bash
gh secret set FB_PAGE_ID --body "123456789012345"
gh secret set FB_PAGE_ACCESS_TOKEN --body "EAABa..."
```

### ❌ Error: "yt-dlp health check failed"

**Cause:** YouTube has JavaScript challenge or anti-bot block

**Current Behavior:** In GitHub Actions (CI environment), the health check runs in "relaxed mode" and allows yt-dlp to continue even if it detects anti-bot measures. This is expected because:
- Shared CI infrastructure is flagged as suspicious by YouTube
- Real authenticated requests (with cookies) often succeed despite the health check
- The actual video download retries with exponential backoff

**Solution:** The pipeline continues even with health check warnings. If actual video downloads fail:

1. **Add YouTube Cookies** (Optional but recommended):
   - Log in to YouTube
   - Export cookies as JSON using a browser extension
   - Set `YT_COOKIES_JSON` secret with the JSON content
   ```bash
   gh secret set YT_COOKIES_JSON --body '{"cookies": [...]}'
   ```

2. **Use Relaxed Mode** (Current Default):
   - Health check automatically runs in relaxed mode in CI
   - Set `YTDLP_HEALTH_STRICT=0` at runtime (already configured)

3. **Install Node.js for JS Runtime**:
   - ✅ Already configured in workflows (actions/setup-node@v4, node 20)
   - Automatically available for yt-dlp to solve JavaScript challenges

### ❌ Error: "Action setup-node requires Node.js 24 but using Node.js 20"

**Cause:** GitHub Actions deprecated Node.js 20

**Status:** ✅ FIXED - Updated to use `actions/setup-node@v4` with node `20`

**Future Warning (June 2, 2026):** Node.js 20 will be deprecated. At that time, update to:
```yaml
uses: actions/setup-node@v4
with:
  node-version: '22'  # or latest LTS
```

### ❌ Error: "Process completed with exit code 1"

**Likely Causes:**
1. Missing environment variables (check GitHub secrets)
2. Invalid configuration in `config/config.yaml`
3. Python import error (check requirements.txt installation)
4. Network connectivity issue to YouTube/APIs

**Debugging:**
```bash
# Run locally with same env vars
export ENVIRONMENT=testing
export FB_PAGE_ID=123456789
export FB_PAGE_ACCESS_TOKEN=token_here
cd cloud
python main.py --dry-run
```

### ❌ Error: "Timeout — Job exceeded maximum execution time"

**Cause:** Video processing is too slow (>60 minutes)

**Solution:**
- Reduce `--once` to `--scan` to skip processing
- Or increase timeout-minutes in workflow

### ⚠️ Warning: "Only images are available" (yt-dlp)

**Cause:** YouTube page has an issue or is serving thumbnail images instead of video info

**Action:** The pipeline continues in relaxed mode. This is handled automatically.

---

## Workflow Files Overview

### AutoReels Pipeline (`pipeline.yml`)
- **Trigger:** Every 4 hours (cron: `0 */4 * * *`) + manual dispatch
- **Runs:** `python main.py <mode>`
- **Modes:** `--once`, `--dry-run`, `--scan`, `--pull-metrics`
- **Duration:** 15-30 minutes (normal), can timeout at 60 min mark
- **Database Cache:** Persists SQLite DBs between runs

### CI — Tests (`ci.yml`)
- **Trigger:** Push to main/develop, PRs to main
- **Runs:** Pytest smoke tests + full test suite
- **Requires:** PostgreSQL service running
- **Coverage:** Python unit tests

### Retry Failed Uploads (`retry_failed.yml`)
- **Trigger:** Every 6 hours (offset from main pipeline)
- **Runs:** `python main.py --retry-failed`
- **Purpose:** Retries failed uploads from dead letter queue

### Weekly Report (`weekly_report.yml`)
- **Trigger:** Every Monday at 9 AM UTC
- **Runs:** `python main.py --weekly-report`
- **Sends:** Email/Slack/Discord notifications

---

## Local Testing Before Committing

### 1. Validate Environment

```bash
cd cloud
python check_env.py          # Check ffmpeg, yt-dlp, Node.js
python validate_env.py --mode dry-run  # Check env variables
```

### 2. Test Pipeline Locally

```bash
# Dry run (no uploads)
python main.py --dry-run

# Scan only (list videos, no processing)
python main.py --scan

# Single real run
python main.py --once
```

### 3. Run Tests

```bash
pytest tests/test_smoke_runtime.py -v
pytest tests/ -v --tb=short
```

---

## Monitoring Workflow Runs

### View Live Logs

1. Go to: https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10/actions
2. Click on the failing workflow run
3. Expand the failed step to see logs
4. Check for:
   - Python import errors
   - Missing environment variables
   - yt-dlp output messages
   - Network timeouts

### Download Artifacts

If run completes fully:
1. Find the run in Actions tab
2. Scroll down to "Artifacts"
3. Download `pipeline-report-<number>` for detailed logs

### Enable Debug Logging

Add this to GitHub Actions:
```yaml
- name: Enable GitHub Actions Debug Logging
  run: |
    echo "ACTIONS_STEP_DEBUG=true" >> $GITHUB_ENV
    echo "AUTOREELS_DEBUG=1" >> $GITHUB_ENV
```

---

## Performance Optimization

### Reduce Run Time

```yaml
# In pipeline.yml, change mode
- name: Run AutoReels pipeline (faster)
  run: |
    cd cloud
    python main.py --scan    # 5 min: scan only
    # vs
    python main.py --once    # 20-30 min: full pipeline
```

### Skip Expensive Steps

```yaml
# Skip yt-dlp health check
- name: Skip health check
  if: ${{ vars.SKIP_HEALTH_CHECK == 'true' }}
  run: echo "Skipping health check"
```

### Cache Python Dependencies

```yaml
# Already configured, but ensure it's enabled
cache: 'pip'
cache-dependency-path: cloud/requirements.txt
```

---

## Rollback Procedures

### If a Recent Commit Breaks CI

```bash
# Show recent commits
gh run list

# View failed run logs
gh run view <RUN_ID> --log

# Cancel ongoing run
gh run cancel <RUN_ID>

# Revert broken commit
git revert <COMMIT_SHA>
git push
```

---

## Contact & Support

- **Documentation:** See [README.md](README.md)
- **Issues:** Check [GitHub Issues](https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10/issues)
- **Questions:** Open a new issue with `[HELP]` prefix

---

## Checklist Before First Production Run

- [ ] All secrets configured in GitHub
- [ ] `config/config.yaml` updated with your YouTube channels
- [ ] `.env` file set and not committed to git
- [ ] Local `python main.py --dry-run` passes
- [ ] `python cloud/check_env.py` reports all tools installed
- [ ] GitHub Actions run by manual trigger completes successfully
- [ ] Database caches populated (`cloud/queue/*.db`)
- [ ] Notifications working (Telegram/Slack/Discord)

---

**Last Updated:** 2026-04-01 | **AutoReels Pro v10.0**
