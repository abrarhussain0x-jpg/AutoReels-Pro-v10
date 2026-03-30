# AutoReels Pro v10 — GitHub Actions Quick Start

Run the full pipeline **free** on GitHub Actions. No server needed.

---

## How it works

GitHub Actions runs your pipeline on a schedule (every 4 hours by default).
SQLite databases (`hooks.db`, `analytics.db`, etc.) are saved between runs
using GitHub's cache, so your ML models keep learning across every run.

```
Every 4 hours:
  GitHub spins up Ubuntu runner (free)
  ↓ Restores your SQLite DBs from cache
  ↓ Installs ffmpeg + Python deps
  ↓ Runs: python cloud/main.py --once
  ↓ Saves SQLite DBs back to cache
  ↓ Uploads run report as artifact
```

---

## Step 1 — Push to GitHub

```bash
# In the project folder:
git init
git add .
git commit -m "AutoReels Pro v10"

# Create a new repo at github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/autoreels-pro.git
git branch -M main
git push -u origin main
```

> **Tip:** Make the repo **public** for unlimited free Actions minutes.
> Private repos get 2,000 min/month free (plenty for this pipeline).

---

## Step 2 — Add secrets

Go to: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

### Required
| Secret | Where to get it |
|--------|----------------|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |
| `FB_PAGE_ID` | Facebook Page URL → About → Page ID |
| `FB_PAGE_ACCESS_TOKEN` | Run `python cloud/get_fb_token.py` locally |

### Optional (notifications)
| Secret | Purpose |
|--------|---------|
| `TELEGRAM_TOKEN` | Alert on pipeline failure (get from @BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat/group ID |
| `SLACK_WEBHOOK` | Slack notifications |
| `DISCORD_WEBHOOK` | Discord notifications |

### Optional (extra platforms)
| Secret | Platform |
|--------|---------|
| `TIKTOK_ACCESS_TOKEN` | TikTok (disabled by default in config) |
| `IG_USER_ID` + `IG_ACCESS_TOKEN` | Instagram |
| `YOUTUBE_CLIENT_ID` + `YOUTUBE_CLIENT_SECRET` + `YOUTUBE_REFRESH_TOKEN` | YouTube Shorts |

---

## Step 3 — Test with dry-run first

1. Go to **Actions tab** in your GitHub repo
2. Click **AutoReels Pipeline** in the left sidebar
3. Click **Run workflow** (top right)
4. Select mode: `--dry-run`
5. Click **Run workflow**

This runs the full pipeline without uploading anything. Check the logs to
confirm everything is working before switching to `--once`.

---

## Step 4 — Go live

Trigger a real run:
1. **Actions → AutoReels Pipeline → Run workflow**
2. Select mode: `--once`
3. Click **Run workflow**

After confirming it works, the pipeline will auto-run every 4 hours via cron.

---

## Workflows included

| File | Schedule | What it does |
|------|----------|-------------|
| `pipeline.yml` | Every 4 hours | Main pipeline: download → clip → caption → upload |
| `ci.yml` | On every push/PR | Runs pytest to catch broken code before merge |
| `weekly_report.yml` | Every Monday 09:00 UTC | Pulls metrics, generates hook/velocity reports |
| `retry_failed.yml` | Every 6 hours | Retries any failed uploads from dead-letter queue |

---

## Change the schedule

Edit `.github/workflows/pipeline.yml` and update the cron:

```yaml
schedule:
  - cron: '0 */4 * * *'   # Every 4 hours  ← default
  - cron: '0 */6 * * *'   # Every 6 hours
  - cron: '0 9,15,21 * * *' # 3× per day at 9am, 3pm, 9pm UTC
  - cron: '0 9 * * *'     # Once per day at 9am UTC
```

---

## View results

- **Run logs**: Actions tab → click any run → click a job
- **Run reports**: Actions → click run → Artifacts → `pipeline-report-N`
- **Weekly reports**: Actions → Weekly Report → Artifacts

---

## Costs

| Item | Cost |
|------|------|
| GitHub Actions compute | **Free** (public repo = unlimited; private = 2,000 min/month) |
| Claude API (Haiku) | ~$0.001 per clip caption |
| Facebook API | Free |
| yt-dlp downloads | Free |

A typical run (1 video × 10 clips × 1 platform) costs roughly **$0.01–0.05** in Claude API.

---

## Troubleshooting

**"No new videos found"**
Your YouTube channels in `cloud/config/config.yaml` may have already-processed
videos. Add newer channels or lower `max_age_days`.

**"yt-dlp challenge failed"**
Export your YouTube cookies and add them to `config/cookies.txt`, then re-push.

**"ANTHROPIC_API_KEY not found"**
Check the secret name is exactly `ANTHROPIC_API_KEY` in your repo secrets.

**Pipeline takes too long**
Reduce `clips_per_video` in `cloud/config/config.yaml` (default: 10 → try 3).

**Want to skip a scheduled run**
Disable the workflow temporarily: Actions → AutoReels Pipeline → ⋯ → Disable workflow.
