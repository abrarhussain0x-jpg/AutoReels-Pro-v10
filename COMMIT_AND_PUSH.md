# How to Commit and Push Changes

Since git is not installed on this system, you have two options:

## Option 1: Install Git Locally & Run Script (Recommended)

### For Windows (PowerShell)

1. **Install Git:**
   - Download from: https://git-scm.com/download/win
   - Or use: `winget install Git.Git`
   - Or use: `choco install git` (if you have Chocolatey)

2. **Run the helper script:**
   ```powershell
   cd "C:\Users\Abrar-Hussain\AutoReels-Pro-v10"
   .\commit_and_push.ps1
   ```

### For macOS / Linux

1. **Install Git:**
   ```bash
   # macOS
   brew install git
   
   # Ubuntu/Debian
   sudo apt-get install git
   
   # Fedora
   sudo dnf install git
   ```

2. **Run the helper script:**
   ```bash
   cd ~/AutoReels-Pro-v10
   bash commit_and_push.sh
   ```

---

## Option 2: Manual Git Commands

If you have git installed elsewhere, run these commands:

```bash
# Navigate to repo
cd "C:\Users\Abrar-Hussain\AutoReels-Pro-v10"

# Configure git (first time only)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# Initialize repo if not already
git init
git remote add origin https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10.git

# Stage all changes
git add --all

# Commit with message
git commit -m "fix: GitHub Actions CI/CD improvements

- Updated GitHub Actions to Node.js 24 compatible versions (v4)
- Upgraded Node version from 18 to 20
- Enhanced yt-dlp health check with better error diagnostics
- Added environment variable validation step in CI workflows
- Added comprehensive GitHub Actions troubleshooting guide
- Support for future Node.js 24 enforcement (June 2, 2026)"

# Push to GitHub
git push -u origin main
# or if main doesn't exist:
git push -u origin master
```

---

## Option 3: GitHub Web Interface

If you don't have git installed and don't want to install it:

1. **Go to:** https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10

2. **Upload files manually:**
   - Click "Add file" → "Upload files"
   - Drag and drop all modified/new files:
     - `.github/workflows/pipeline.yml`
     - `.github/workflows/retry_failed.yml`
     - `cloud/utils/yt_dlp_health_check.py`
     - `GITHUB_ACTIONS_TROUBLESHOOTING.md`
     - `FIXES_APPLIED.md`
   - Write commit message (see above)
   - Click "Commit changes"

---

## What Gets Committed

### Modified Files (3)
- `.github/workflows/pipeline.yml`
  - Updated Node.js v3→v4
  - Added validation step 6.4
  
- `.github/workflows/retry_failed.yml`
  - Updated Node.js v3→v4
  - Added validation step

- `cloud/utils/yt_dlp_health_check.py`
  - Added timeout exception handling
  - Added diagnostic suggestions
  - Improved error logging

### New Files (3)
- `GITHUB_ACTIONS_TROUBLESHOOTING.md`
  - Comprehensive CI/CD troubleshooting guide
  
- `FIXES_APPLIED.md`
  - Technical documentation of all changes
  
- `commit_and_push.sh` / `commit_and_push.ps1`
  - Helper scripts (you can delete after pushing)

---

## Verification

After pushing, verify the changes:

1. **Check GitHub:**
   - Visit: https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10
   - Should see a new commit in the history
   - Check "Actions" tab to monitor workflow runs

2. **Verify Workflows:**
   - Go to: Actions tab
   - Should show recent workflow runs
   - Check for green checkmarks ✅

3. **Set GitHub Secrets:**
   - Go to: Settings → Secrets and variables → Actions
   - Add required secrets:
     - `ANTHROPIC_API_KEY`
     - `FB_PAGE_ID`
     - `FB_PAGE_ACCESS_TOKEN`
     - `ENVIRONMENT=github_actions`

---

## Troubleshooting

### "fatal: not a git repository"
- Solution: Run `git init` first, then `git remote add origin https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10.git`

### "fatal: 'origin' does not appear to be a 'git' repository"
- Solution: Make sure you cloned from the correct URL

### "fatal: could not read Username"
- Solution: You need to authenticate with GitHub
  - On first push, you'll be asked for credentials
  - Or set up SSH keys: https://docs.github.com/en/authentication/connecting-to-github-with-ssh

### "failed to push some refs to 'origin'"
- Solution: Your branch might be behind remote
  - Run: `git pull origin main --rebase`
  - Then: `git push origin main`

---

## Next Steps After Push

1. ✅ Verify commit appears in GitHub history
2. ✅ Check Actions tab for workflow runs
3. ✅ Set GitHub secrets (see guide above)
4. ✅ Trigger first pipeline manually: Actions → AutoReels Pipeline → Run workflow → --dry-run
5. ✅ Monitor logs for "Validate environment variables" success
6. ✅ Read GITHUB_ACTIONS_TROUBLESHOOTING.md for next steps

---

**Need Help?** Check [GITHUB_ACTIONS_TROUBLESHOOTING.md](GITHUB_ACTIONS_TROUBLESHOOTING.md) for detailed guidance.
