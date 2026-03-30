<#
PowerShell helper to install required system and Python packages on Windows.
Usage: Run in PowerShell as Administrator for system package installs, or without admin to install Python packages for the current user:
  powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
#>

Write-Host "Checking Python and pip..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found in PATH. Please install Python 3.8+ from https://www.python.org/ and re-run this script." -ForegroundColor Yellow
    exit 1
}

Write-Host "Checking for winget or Chocolatey (for ffmpeg)..."
$hasWinget = (Get-Command winget -ErrorAction SilentlyContinue) -ne $null
$hasChoco = (Get-Command choco -ErrorAction SilentlyContinue) -ne $null

if ($hasWinget) {
    Write-Host "Installing ffmpeg via winget..."
    winget install --id Gyan.FFmpeg.Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
} elseif ($hasChoco) {
    Write-Host "Installing ffmpeg via Chocolatey..."
    choco install ffmpeg -y
} else {
    Write-Host "No supported Windows package manager found (winget/choco). Please install ffmpeg manually from https://www.gyan.dev/ffmpeg/builds/ and add ffmpeg.exe to your PATH." -ForegroundColor Yellow
}

Write-Host "Installing Python packages (user scope)..."
# Install requirements.txt if present
$req = Join-Path $PSScriptRoot 'requirements.txt'
if (Test-Path $req) {
    Write-Host "Found requirements.txt, installing..."
    python -m pip install --user -r $req
}

Write-Host "Installing additional required packages: yt-dlp, PyYAML, Pillow, imagehash, psutil"
python -m pip install --user yt-dlp PyYAML Pillow imagehash psutil

# If .env exists, recommend python-dotenv for running via PowerShell
if (Test-Path (Join-Path $PSScriptRoot '.env')) {
    Write-Host "Detected .env - installing python-dotenv (recommended)"
    python -m pip install --user python-dotenv
}

Write-Host "Setup script finished. Verify ffmpeg and python packages are available in a new shell." -ForegroundColor Green
