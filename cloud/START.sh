#!/bin/bash
# ═══════════════════════════════════════════════
#  AUTO-REELS PRO v10 — START SCRIPT
#  YOUR PAGE: set FB_PAGE_ID in your .env
#  Run this on your server to go live
# ═══════════════════════════════════════════════

echo "🚀 Starting AUTO-REELS PRO v10..."

# Load credentials
set -a
source .env
set +a

# Step 1: Install deps (first run only)
if ! command -v yt-dlp &>/dev/null; then
    echo "📦 Installing yt-dlp..."
    pip3 install yt-dlp --quiet
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "📦 Installing ffmpeg..."
    sudo apt-get install -y ffmpeg -qq 2>/dev/null || brew install ffmpeg 2>/dev/null
fi

pip3 install PyYAML Pillow imagehash psutil schedule --quiet

# Step 2: Get YouTube cookies (IMPORTANT - do this once)
if [ ! -f config/cookies.txt ]; then
    echo ""
    echo "⚠️  COOKIES NEEDED - Run this once in your browser's terminal:"
    echo "   yt-dlp --cookies-from-browser chrome --cookies config/cookies.txt --skip-download https://youtube.com"
    echo ""
fi

# Step 3: Health check
echo "🔍 Running health check..."
python3 health_check.py

# Step 4: Test run first?
echo ""
read -p "Do a TEST run first (no real uploads)? [Y/n] " test_first
if [[ "$test_first" != "n" && "$test_first" != "N" ]]; then
    echo "🧪 Running DRY RUN test..."
    AUTOREELS_FORCE_RUN=1 AUTOREELS_DRY_RUN=1 python3 run_pipeline.py --dry-run
    echo ""
    read -p "Test done. Start REAL daemon (posts to your Facebook page)? [y/N] " go_live
    if [[ "$go_live" == "y" || "$go_live" == "Y" ]]; then
        echo "🔥 Starting LIVE daemon..."
        python3 run_pipeline.py --daemon
    fi
else
    echo "🔥 Starting LIVE daemon..."
    python3 run_pipeline.py --daemon
fi
