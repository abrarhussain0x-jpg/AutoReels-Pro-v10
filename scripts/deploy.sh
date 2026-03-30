#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# AUTO-REELS PRO v10.0 — QUICK START DEPLOYMENT SCRIPT
# ═══════════════════════════════════════════════════════════════════════════
# Run: bash scripts/deploy.sh

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 AutoReels Pro v10 — Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ .env file not found!"
    echo "   Run: cp .env.example .env && edit .env with your secrets"
    exit 1
fi

# Load environment
set -a
source "$PROJECT_ROOT/.env"
set +a

# Check required secrets
check_secret() {
    local var_name=$1
    local var_value=$(eval echo \$$var_name)
    if [ -z "$var_value" ] || [ "$var_value" = "sk-ant-v1-..." ]; then
        echo "❌ Missing: $var_name"
        return 1
    fi
    echo "✅ $var_name: set"
    return 0
}

echo "📋 Checking configuration..."
check_secret "ANTHROPIC_API_KEY" || exit 1
check_secret "FB_PAGE_IDS" || true
check_secret "DATABASE_URL" || true
check_secret "REDIS_URL" || true

echo ""
echo "📦 Installing dependencies..."
cd "$PROJECT_ROOT/cloud"
python -m pip install -q -r requirements.txt

echo ""
echo "🗄️  Setting up database..."
python -c "
from src.database.schema import Base, create_indexes
from sqlalchemy import create_engine
import os

db_url = os.getenv('DATABASE_URL', 'postgresql://localhost/autoreels')
engine = create_engine(db_url)
Base.metadata.create_all(engine)
create_indexes(engine)
print('✅ Database schema created')
"

echo ""
echo "🐳 Starting Docker services..."
cd "$PROJECT_ROOT"
docker-compose up -d postgres redis web celery-worker celery-beat flower

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Health check
echo "🏥 Health check..."
if curl -f http://localhost:5000/health 2>/dev/null; then
    echo "✅ Web API is healthy"
else
    echo "⚠️  Web API not ready yet (will be ready in ~30s)"
fi

echo ""
echo "✨ DEPLOYMENT COMPLETE!"
echo ""
echo "📊 Dashboard: http://localhost:5000"
echo "📈 Celery Monitor: http://localhost:5555"
echo "🗄️  Database: postgresql://autoreels:...@localhost:5432/autoreels"
echo "🔴 Redis: redis://localhost:6379/0"
echo ""
echo "Next steps:"
echo "  1. View logs: docker-compose logs -f web"
echo "  2. Run tests: pytest cloud/tests/"
echo "  3. Start pipeline: python cloud/run_pipeline.py"
echo ""
echo "GitHub Secrets to set (for CI/CD):"
echo "  - ANTHROPIC_API_KEY"
echo "  - DATABASE_URL (production)"
echo "  - REDIS_URL (production)"
echo "  - SLACK_WEBHOOK"
echo ""
