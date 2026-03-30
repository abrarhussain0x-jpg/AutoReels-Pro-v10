# AUTO-REELS PRO v10.0 — Autonomous AI Content Engine

---

## ⚠️ Legal & Content Rights Notice

This tool must only be used with video content that you:
- **Own outright**, or
- **Have explicit written permission** from the copyright holder to download, clip, and republish

Downloading YouTube videos without permission violates [YouTube's Terms of Service §5.1(K)](https://www.youtube.com/t/terms). Republishing third-party content without a license may constitute copyright infringement under DMCA and applicable law.

The example channel URLs in `config/config.yaml` are placeholders only. Replace them with your own licensed content sources before running the pipeline.

---


Fully automated YouTube → Facebook Reels · TikTok · Instagram Reels · YouTube Shorts · Threads pipeline.
2× more real than v9 with production-grade intelligence, failsafe retry, multi-account rotation, and real-time engagement learning.

---

## What's New in v10 vs v9

### 🎯 Viral Hook Intelligence Engine (`src/intelligence/hook_optimizer.py`)
- UCB1-based hook PHRASE learning — not just angle selection
- Tracks which exact hook text drives 3-second retention per platform × niche × angle
- HookLibrary (SQLite: `hooks.db`) with 30 seed phrases per angle
- Auto-retrains from real retention after every `--pull-metrics`
- Expose: `get_best_hook(platform, niche, angle)` → winning phrase

### ✂️ Scene-Aware Smart Clipping (`src/processor/scene_clipper.py`)
- Replaces fixed-length clips with natural scene-boundary cuts via ffprobe
- Whisper VAD word timestamps enforce sentence-boundary endings
- Per-clip scoring: audio_energy + motion_score + transcript density
- Result: clips that feel like intentional TV episode breaks

### 💬 Word-Level Karaoke Captions (`src/processor/subtitle_engine_v2.py`)
- faster-whisper with `word_timestamps=True` — each word pops at its exact timestamp
- Claude Haiku detects the "power word" per sentence → highlighted in accent color
- Configurable: font_size, accent_color (#FFE600 default), position, shadow
- Burns directly into video via FFmpeg ASS filter

### 👥 Multi-Account Rotation (`src/publisher/account_rotator.py`)
- Multiple Facebook/TikTok/Instagram accounts per platform
- Round-robin distribution; auto-rotates on daily limit exhaustion
- Per-account circuit breaker: auth failure → skip account for 30 min
- Config: `facebook.accounts[]` with `page_id` + `access_token` + `daily_limit`

### 📈 Engagement Velocity Tracking (`src/analytics/velocity_tracker.py`)
- Metric pulls at 1h, 6h, 24h, 72h after upload (multi-point curves)
- Velocity = views_6h − views_1h / 5 hours
- Viral threshold: >500 views/hour at 6h → immediate alert
- Feeds slope features into GrowthPredictor

### 💬 Comment Sentiment Bot (`src/engagement/comment_bot.py`)
- Fetches top 20 comments per post at 24h + 48h
- Claude Haiku classifies: positive / negative / question / spam
- Auto-replies to genuine questions using platform API
- Alerts when negative sentiment > 30%

### 🖼️ Thumbnail A/B Testing (`src/processor/thumbnail_ab.py`)
- 3 variants per clip:
  - Variant A: Face-centered gradient + hook text overlay
  - Variant B: High-contrast frame + bold title
  - Variant C: Blurred background + centered text
- Tracks CTR per variant; UCB1 weight update after 24h
- Next video auto-selects winning style per niche

### 🕐 Smart Schedule Optimizer v2 (`src/optimizer/time_optimizer_v2.py`)
- Per-NICHE × PLATFORM optimal windows (not just per-platform)
- Day-of-week intelligence per niche (anime peaks Fri/Sat/Sun)
- Auto-shift: engagement drop >20% → logs warning + recommends shift

### 🛡️ Failsafe Retry Architecture (`src/resilience/retry_engine.py`)
- Exponential backoff: 1s → 2s → 4s → 8s → 16s (max 5 retries)
- Error classification: rate_limit / auth_error / server_error / invalid_media
- Per-platform circuit breaker: 3 failures → 30-min open
- Dead letter queue (SQLite: `failed.db`): auto-retried on next daemon run

### 📊 Real-Time Dashboard v2 (`src/dashboard/app_v2.py`)
- `/` Pipeline status, recent uploads
- `/analytics` Daily views chart + platform breakdown
- `/abtesting` Angle win rates + hook leaderboard
- `/accounts` Per-account rotation + circuit status
- `/velocity` Live sparkline velocity curves
- `/schedule` Optimal window heatmap (niche × day)
- `/failed` Dead letter queue viewer + retry button
- Auto-refresh every 30s, dark theme, mobile-responsive

---

## All v9 Features (preserved)

| Feature | Details |
|---------|---------|
| Narrative Arc Engine | TV-show arc (SETUP→CLUE_DROP→ESCALATION→REVELATION) |
| Growth Predictor | ML engagement predictor, mini-batch gradient descent |
| Batch Content Gen | All clips × platforms in 1 API call |
| A/B Angle Testing | UCB1, 6 angles, per-platform weights |
| Auto-Repost | Top 15% re-uploaded weekly |
| PIL Thumbnails | 6 themes, face-centering |
| VideoScorer | 7-component composite score |
| All Notifications | Slack + Telegram + Discord + Email |

---

## Quick Start

### 1. Configure
```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY + FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN
```

### 2. Install
```bash
cd cloud
pip install -r requirements.txt
```

### 3. Validate
```bash
python main.py --check
```

### 4. Run
```bash
python main.py --dry-run      # test everything without uploading
python main.py --once         # one real run
python main.py --daemon       # continuous 15-min loop
python main.py --dashboard    # start dashboard at http://localhost:8888
```

### System prerequisites (important)

This project requires a few system-level dependencies in addition to Python packages:

- `ffmpeg` — required for all video processing. Install a recent build and ensure `ffmpeg` is on `PATH`.
- `yt-dlp` — used to scrape YouTube metadata and download videos (installed via `pip` in `cloud/requirements.txt`).
- `Node.js` (optional but recommended) — some YouTube pages use a JS challenge (EJS). If `yt-dlp` reports "challenge solving failed" or "Only images are available", install Node and follow the `yt-dlp` EJS setup.

Quick checks:
```powershell
python -m pip install -r cloud/requirements.txt
python cloud/check_env.py
```

If `cloud/check_env.py` reports a JS challenge, install Node.js (Windows example using Chocolatey):
```powershell
choco install nodejs -y
python -m pip install -U yt-dlp
# Follow: https://github.com/yt-dlp/yt-dlp/wiki/EJS
```

### Troubleshooting

- If discovery returns "No new videos found" but `yt-dlp` listings show videos, run `python cloud/check_env.py` to confirm `yt-dlp` can extract formats.
- If you see logs like "Only images are available" or "challenge solving failed", fix the JS solver (Node + EJS) and re-run.
- To test end-to-end without discovery, you can enqueue a known downloadable video with `enqueue_test.py` then run a dry-run:
```powershell
python enqueue_test.py
$env:AUTOREELS_DRY_RUN="1"; python cloud/run_pipeline.py --dry-run
```

### Notes
- Keep `.env` in `cloud/.env` and DO NOT commit it. Fill `FB_PAGE_ACCESS_TOKEN` and any platform tokens before running real uploads.
- Use `AUTOREELS_FORCE_RUN=1` environment variable to bypass time-window gates during tests.


---

## All CLI Commands

```bash
# Pipeline
python main.py --once              # single run
python main.py --daemon            # continuous
python main.py --dry-run           # no uploads
python main.py --scan              # list candidates only
python main.py --check             # token validation
python main.py --pull-metrics      # pull engagement + retrain models

# Reports (v9)
python main.py --time-windows      # posting windows
python main.py --arc-report        # narrative arc plan
python main.py --report            # weekly summary

# Reports (v10)
python main.py --hook-report       # hook phrase leaderboard
python main.py --velocity-report   # engagement velocity curves
python main.py --rotate-accounts   # account rotation status
python main.py --retry-failed      # retry dead letter queue
python main.py --thumbnail-report  # thumbnail A/B results
python main.py --comment-sweep     # run comment bot
python main.py --dashboard         # live dashboard
```

---

## New DB Files (v10)

| File | Contents |
|------|---------|
| `queue/hooks.db` | Hook phrase UCB1 weights per platform/niche/angle |
| `queue/account_rotation.db` | Per-account daily upload counters + circuit state |
| `queue/velocity.db` | Multi-point engagement time-series curves |
| `queue/comments.db` | Comment sentiment + auto-reply records |
| `queue/thumbnail_ab.db` | Thumbnail variant A/B CTR results |
| `queue/failed.db` | Dead letter queue for failed uploads |

---

## Architecture v10

```
YouTube Channels
      │
      ▼
YouTubeMonitor ──► VideoScorer ──► DecisionEngine
                                        │
                              ┌─────────┴──────────┐
                        PROCESS              SKIP/DEFER
                              │
                              ▼
                    ┌─────────────────────┐
                    │  NarrativeArcEngine  │  (v9)
                    └─────────────────────┘
                              │
                    ┌─────────────────────┐
                    │  ContentGenerator    │  (v9 batch)
                    │  + HookOptimizer     │  ← v10 NEW
                    └─────────────────────┘
                              │
                    ┌─────────────────────┐
                    │  SceneClipper        │  ← v10 NEW
                    │  SubtitleEngineV2    │  ← v10 NEW
                    │  ThumbnailABEngine   │  ← v10 NEW
                    └─────────────────────┘
                              │
                    ┌─────────────────────┐
                    │  GrowthPredictor     │  (v9 gate)
                    │  TimeOptimizerV2     │  ← v10 UPGRADED
                    └─────────────────────┘
                              │
                    ┌─────────────────────┐
                    │  AccountRotator      │  ← v10 NEW
                    │  RetryEngine         │  ← v10 NEW
                    └─────────────────────┘
                              │
              ┌───────────────┼───────────────────┬──────────┐
         Facebook          TikTok           Instagram   YouTube   Threads
              │
              ▼
        VelocityTracker (1h/6h/24h/72h pulls) ← v10 NEW
              │
              ▼
        CommentBot (24h/48h sweep) ← v10 NEW
              │
              ▼
        ABEngine + HookOptimizer + ThumbnailAB → retrain
```

---

## License
MIT — Use freely, modify, deploy. Built for creators.
