#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  AUTO-REELS PRO v10 — One-Command Setup Script
#  Works on Ubuntu 20.04+ / Debian 11+ / any Linux VPS
#  Usage: bash setup.sh
# ═══════════════════════════════════════════════════════════

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; exit 1; }
info() { echo -e "${BLUE}→  $1${NC}"; }

echo -e "\n${BLUE}╔══════════════════════════════════════════╗"
echo -e "║   AUTO-REELS PRO v10 — Setup Script      ║"
echo -e "╚══════════════════════════════════════════╝${NC}\n"

# ── System check ─────────────────────────────────────────────
info "Checking system..."
[[ "$(uname -s)" == "Linux" ]] || fail "Linux required"
python3 --version &>/dev/null || fail "Python3 not found. Run: sudo apt install python3"
ok "System: Linux + Python3"

# ── Install ffmpeg ────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    info "Installing ffmpeg..."
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg -qq
    ok "ffmpeg installed"
else
    ok "ffmpeg: $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3)"
fi

# ── Install Python packages ───────────────────────────────────
info "Installing Python packages..."
pip3 install -q --upgrade pip
pip3 install -q \
    yt-dlp \
    PyYAML \
    requests \
    flask \
    Pillow \
    imagehash \
    schedule \
    psutil
ok "Python packages installed"

# ── Create directory structure ────────────────────────────────
info "Creating directories..."
mkdir -p queue config logs tmp
touch queue/.gitkeep logs/.gitkeep
ok "Directories created"

# ── Create .env if not exists ─────────────────────────────────
if [ ! -f .env ]; then
    cp ../.env.example .env 2>/dev/null || cat > .env << 'ENVEOF'
# AUTO-REELS PRO v10 — Fill these in!
FB_PAGE_ID=your_page_id_here
FB_PAGE_ACCESS_TOKEN=your_long_lived_token_here
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK=
ENVEOF
    ok ".env created — EDIT IT with your tokens!"
    warn "Open .env and add your Facebook Page ID and Access Token"
else
    ok ".env already exists"
fi

# ── Validate config ───────────────────────────────────────────
info "Validating config..."
if python3 health_check.py 2>/dev/null | grep -q "ALL CHECKS PASSED"; then
    ok "Health check passed"
else
    warn "Some health checks failed — run: python3 health_check.py"
fi

# ── Create cron job (optional) ────────────────────────────────
echo ""
read -p "Install cron job to run every 15 minutes? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CRON_CMD="*/15 * * * * cd $SCRIPT_DIR && python3 run_pipeline.py >> logs/cron.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "run_pipeline"; echo "$CRON_CMD") | crontab -
    ok "Cron job installed (every 15 min)"
fi

# ── Create systemd service (optional) ────────────────────────
echo ""
read -p "Install as systemd daemon service? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SERVICE="[Unit]
Description=Auto-Reels PRO v10
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=python3 run_pipeline.py --daemon
Restart=always
RestartSec=60
StandardOutput=append:$SCRIPT_DIR/logs/service.log
StandardError=append:$SCRIPT_DIR/logs/service.log

[Install]
WantedBy=multi-user.target"
    echo "$SERVICE" | sudo tee /etc/systemd/system/autoreels.service > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable autoreels
    ok "Systemd service installed"
    echo -e "  ${BLUE}Start:  sudo systemctl start autoreels"
    echo -e "  Status: sudo systemctl status autoreels"
    echo -e "  Logs:   journalctl -u autoreels -f${NC}"
fi

echo -e "\n${GREEN}╔══════════════════════════════════════════╗"
echo -e "║         SETUP COMPLETE! 🎉               ║"
echo -e "╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Edit ${BLUE}.env${NC} — add your FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN"
echo -e "  2. Edit ${BLUE}config/config.yaml${NC} — set your YouTube channels + channel name"
echo -e "  3. Run: ${BLUE}python3 health_check.py${NC} — verify everything is ready"
echo -e "  4. Run: ${BLUE}python3 run_pipeline.py --dry-run${NC} — test without uploading"
echo -e "  5. Run: ${BLUE}python3 run_pipeline.py${NC} — go live!"
echo ""
