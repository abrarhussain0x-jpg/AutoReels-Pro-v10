# AutoReels Pro v10 — Commit and Push Script (PowerShell)
# Run this on your local machine with git installed

$RepoPath = "C:\Users\Abrar-Hussain\AutoReels-Pro-v10"
$CommitMessage = @"
fix: GitHub Actions CI/CD improvements

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
- FIXES_APPLIED.md
"@

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "AutoReels Pro v10 — Commit & Push" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Change to repo directory
Push-Location $RepoPath -ErrorAction Stop
Write-Host "📁 Working in: $(Get-Location)" -ForegroundColor Green
Write-Host ""

# Check git is installed
$gitPath = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitPath) {
    Write-Host "❌ Git is not installed" -ForegroundColor Red
    Write-Host "Install from: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Git found: $(git --version)" -ForegroundColor Green
Write-Host ""

# Configure git (first time only)
Write-Host "🔧 Configuring git..." -ForegroundColor Cyan
git config --global user.name "AutoReels Bot" 2>$null
git config --global user.email "bot@autoreels.dev" 2>$null

# Check if already in git repo
if (-not (Test-Path ".git")) {
    Write-Host "⚠️  Not a git repository. Initializing..." -ForegroundColor Yellow
    git init
    git remote add origin https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10.git
}

Write-Host ""
Write-Host "📊 Current status:" -ForegroundColor Cyan
git status --short

Write-Host ""
Write-Host "📝 Staging files..." -ForegroundColor Cyan
git add --all

Write-Host ""
Write-Host "💾 Committing changes..." -ForegroundColor Cyan
git commit -m $CommitMessage
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Nothing to commit or commit failed" -ForegroundColor Yellow
    git status
    exit 1
}

Write-Host ""
Write-Host "🚀 Pushing to GitHub..." -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Push to 'main' failed, trying 'master'..." -ForegroundColor Yellow
    git push -u origin master
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Push failed. Possible causes:" -ForegroundColor Red
    Write-Host "  - Not authenticated with GitHub" -ForegroundColor Yellow
    Write-Host "  - Remote branch doesn't exist" -ForegroundColor Yellow
    Write-Host "  - No internet connection" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Try manually:" -ForegroundColor Cyan
    Write-Host "  git push origin main" -ForegroundColor White
    Write-Host "  (or git push origin master)" -ForegroundColor White
    Pop-Location
    exit 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ SUCCESS! Changes pushed to GitHub" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Next steps:" -ForegroundColor Cyan
Write-Host "  1. Visit: https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10" -ForegroundColor White
Write-Host "  2. Check Actions tab for workflow status" -ForegroundColor White
Write-Host "  3. Set GitHub secrets if not already done" -ForegroundColor White
Write-Host ""
Write-Host "🔐 Required secrets:" -ForegroundColor Cyan
Write-Host "  - ANTHROPIC_API_KEY" -ForegroundColor White
Write-Host "  - FB_PAGE_ID" -ForegroundColor White
Write-Host "  - FB_PAGE_ACCESS_TOKEN" -ForegroundColor White
Write-Host "  - ENVIRONMENT" -ForegroundColor White
Write-Host ""

Pop-Location
