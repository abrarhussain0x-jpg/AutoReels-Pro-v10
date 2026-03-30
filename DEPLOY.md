# AUTO-REELS PRO v10 — Complete Deploy Guide

## Prerequisites

| Tool | Install Command | Required? |
|------|----------------|-----------|
| Python 3.9+ | `sudo apt install python3 python3-pip` | ✅ Yes |
| ffmpeg | `sudo apt install ffmpeg` | ✅ Yes |
| yt-dlp | `pip install yt-dlp` | ✅ Yes |
| Pillow | `pip install Pillow` | ✅ Yes (thumbnails) |
| PyYAML | `pip install PyYAML` | ✅ Yes |
| Flask | `pip install flask` | Optional (dashboard) |
| imagehash | `pip install imagehash` | Optional (dedup) |
| psutil | `pip install psutil` | Optional (monitoring) |

---

## Quick Deploy (5 minutes)

```bash
# 1. Run automated setup
bash setup.sh

# 2. Get your Facebook token (interactive wizard)
python3 get_fb_token.py

# 3. Add your YouTube channels
python3 channel_manager.py --add https://www.youtube.com/@YourChannel/videos
python3 channel_manager.py --list

# 4. Get cookies for yt-dlp (required for some videos)
yt-dlp --cookies-from-browser chrome \
  --cookies config/cookies.txt \
  --skip-download https://youtube.com

# 5. Run health check
python3 health_check.py

# 6. Test (no uploads)
python3 run_pipeline.py --dry-run

# 7. Go live!
python3 run_pipeline.py
```

---

## Configuration Guide

### Minimum config (edit `config/config.yaml`):

```yaml
niche: "movie"          # movie | anime | kdrama | horror | documentary

channels:
  - url: "https://www.youtube.com/@YourChannel/videos"
    max_videos_per_run: 2

branding:
  channel_name: "YourPageName"  # Your Facebook page name
  theme: "cinematic"             # classic | neon | dark | minimal | fire | golden

facebook:
  accounts:
    - page_id: "YOUR_PAGE_ID"
      access_token: "YOUR_TOKEN"
      daily_limit: 10
  disabled: false

daily_upload_limit: 5
clips_per_video: 8
clip_length_seconds: 50
```

### Advanced settings:

```yaml
# Quality
output:
  width: 1080
  height: 1920
  crf: 20              # Lower = better quality (18-28 range)
  preset: "medium"     # ultrafast fast medium slow

# Enhancement
color_grade: true
ken_burns_zoom: true

# Posting schedule (audience time)
audience_timezone: "America/New_York"
upload_times: ["09:00", "12:00", "18:00", "21:00"]

# TikTok (optional)
tiktok:
  disabled: false
  accounts:
    - access_token: "YOUR_TIKTOK_TOKEN"
```

---

## All CLI Commands

```bash
# Pipeline
python3 run_pipeline.py              # run once and exit
python3 run_pipeline.py --daemon     # run every 15 min forever
python3 run_pipeline.py --dry-run    # test, no uploads
python3 run_pipeline.py --queue-status  # show job queue

# Setup
python3 setup.sh                     # one-command setup
python3 get_fb_token.py              # get Facebook token (wizard)
python3 health_check.py              # check all dependencies + tokens
python3 channel_manager.py --list    # list channels
python3 channel_manager.py --add URL # add a channel
python3 channel_manager.py --stats   # per-channel performance

# Analytics
python3 main.py --weekly-report      # generate + send weekly report
python3 main.py --velocity-report    # engagement velocity curves
python3 main.py --hook-report        # best hooks leaderboard
python3 main.py --thumbnail-report   # A/B thumbnail results
python3 main.py --rotate-accounts    # account rotation status
python3 main.py --time-windows       # optimal posting windows

# Maintenance
python3 main.py --system-status      # CPU/RAM/Disk health
python3 main.py --cookie-status      # yt-dlp cookie freshness
python3 main.py --cleanup            # delete old tmp files
python3 main.py --retry-failed       # retry failed uploads
python3 main.py --check              # validate all tokens
python3 main.py --pull-metrics       # fetch engagement data

# Dashboard
python3 main.py --dashboard          # http://localhost:8888
```

---

## Run 24/7 on a Server

### Option A: Cron (simplest)
```bash
# Every 15 minutes:
*/15 * * * * cd /path/to/autoreels-v10/cloud && python3 run_pipeline.py >> logs/cron.log 2>&1

# Weekly report every Sunday at 9am:
0 9 * * 0 cd /path/to/autoreels-v10/cloud && python3 main.py --weekly-report >> logs/report.log 2>&1
```

### Option B: Systemd service
```bash
bash setup.sh   # choose "yes" to install systemd service
sudo systemctl start autoreels
sudo systemctl status autoreels
journalctl -u autoreels -f    # live logs
```

### Option C: Docker
```bash
cd autoreels-v10
# Edit cloud/.env with your tokens
docker-compose up -d
docker logs -f autoreels-pro    # live logs
```

---

## Getting Your Facebook Token (Manual)

1. Go to https://developers.facebook.com/apps/ → Create App → Business
2. Go to Tools → Graph API Explorer
3. Select your app, click "Generate Access Token"
4. Add permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`
5. Click the little user icon → "Get Page Access Token"
6. Copy the token and your Page ID
7. Add to `config/config.yaml` or `.env`

**Token expires in 60 days.** The TokenRefresher will alert you 7 days before expiry.

---

## Adding TikTok

1. Go to https://developers.tiktok.com/ → Create App
2. Add product: Content Posting API
3. Generate access token
4. Add to config:
```yaml
tiktok:
  disabled: false
  accounts:
    - access_token: "YOUR_TOKEN"
```

---

## Troubleshooting

| Problem | Solution |
|---------|---------|
| `yt-dlp not found` | `pip install yt-dlp` |
| `ffmpeg not found` | `sudo apt install ffmpeg` |
| `No videos found` | Check cookies: `python3 main.py --cookie-status` |
| `FB token invalid` | Run `python3 get_fb_token.py` |
| `Low disk space` | Run `python3 main.py --cleanup` |
| Upload fails | Check `python3 main.py --retry-failed` |
| Bad quality clips | Lower CRF in config (18-20 = high quality) |
| Clips look dark | Change `theme: "golden"` in branding config |

---

## Folder Structure

```
autoreels-v10/
├── cloud/
│   ├── run_pipeline.py      ← MAIN entry point (use this to run)
│   ├── main.py              ← CLI tool for reports + management
│   ├── health_check.py      ← Pre-flight validator
│   ├── get_fb_token.py      ← Facebook token wizard
│   ├── channel_manager.py   ← Add/remove YouTube channels
│   ├── setup.sh             ← One-command setup
│   ├── config/
│   │   ├── config.yaml      ← All settings here
│   │   └── cookies.txt      ← yt-dlp cookies (you create this)
│   ├── queue/               ← All SQLite databases (auto-created)
│   │   ├── jobs.db          ← Job queue + processing history
│   │   ├── analytics.db     ← Upload performance data
│   │   ├── velocity.db      ← Engagement time-series
│   │   ├── hooks.db         ← Hook phrase performance
│   │   ├── failed.db        ← Failed uploads (retry queue)
│   │   └── ...              ← Other tracking DBs
│   ├── logs/                ← Log files (auto-created)
│   └── tmp/                 ← Temp video files (auto-cleaned)
├── Dockerfile
└── docker-compose.yml
```
