#!/bin/bash
# AutoReels Pro v10 — Commit and Push Script
# Run this on your local machine with git installed

set -e  # Exit on any error

REPO_PATH="C:\Users\Abrar-Hussain\AutoReels-Pro-v10"
COMMIT_MESSAGE="fix: GitHub Actions CI/CD improvements

- Updated GitHub Actions to Node.js 24 compatible versions (v4)
- Upgraded Node version from 18 to 20
- Enhanced yt-dlp health check with better error diagnostics
- Added environment variable validation step in CI workflows
- Added comprehensive GitHub Actions troubleshooting guide
- Support for future Node.js 24 enforcement (June 2, 2026)

Files modified:
- .github/workflows/pipeline.yml
- .github/workflows/retry_failed.yml
- cloud/utils/yt_dlp_health_check.py

Files created:
- GITHUB_ACTIONS_TROUBLESHOOTING.md
- FIXES_APPLIED.md"

echo "=========================================="
echo "AutoReels Pro v10 — Commit & Push"
echo "=========================================="
echo ""

# Change to repo directory
cd "$REPO_PATH" || {
    echo "❌ Repository not found at: $REPO_PATH"
    echo "Please update REPO_PATH in this script"
    exit 1
}

echo "📁 Working in: $(pwd)"
echo ""

# Check git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed"
    echo "Install from: https://git-scm.com/download/win"
    exit 1
fi

echo "✅ Git found: $(git --version)"
echo ""

# Configure git (first time only)
echo "🔧 Configuring git..."
git config --global user.name "AutoReels Bot" 2>/dev/null || true
git config --global user.email "bot@autoreels.dev" 2>/dev/null || true

# Check if already in git repo
if [ ! -d ".git" ]; then
    echo "⚠️  Not a git repository. Initializing..."
    git init
    git remote add origin https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10.git
fi

echo ""
echo "📊 Current status:"
git status --short

echo ""
echo "📝 Staging files..."
git add --all

echo ""
echo "💾 Committing changes..."
git commit -m "$COMMIT_MESSAGE" || {
    echo "⚠️  Nothing to commit or commit failed"
    git status
    exit 1
}

echo ""
echo "🚀 Pushing to GitHub..."
git push -u origin main || git push -u origin master || {
    echo "❌ Push failed. Possible causes:"
    echo "  - Not authenticated with GitHub"
    echo "  - Remote branch doesn't exist"
    echo "  - No internet connection"
    echo ""
    echo "Try manually:"
    echo "  git push origin main"
    echo "  (or git push origin master)"
    exit 1
}

echo ""
echo "=========================================="
echo "✅ SUCCESS! Changes pushed to GitHub"
echo "=========================================="
echo ""
echo "📋 Next steps:"
echo "  1. Visit: https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10"
echo "  2. Check Actions tab for workflow status"
echo "  3. Set GitHub secrets if not already done"
echo ""
echo "🔐 Required secrets:"
echo "  - ANTHROPIC_API_KEY"
echo "  - FB_PAGE_ID"
echo "  - FB_PAGE_ACCESS_TOKEN"
echo "  - ENVIRONMENT"
