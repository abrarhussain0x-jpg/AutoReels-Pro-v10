# Pre-push checks: syntax + dry-run smoke test
param()

Write-Host "Running compile check..."
python -m compileall cloud/src

Write-Host "Running pipeline dry-run (no uploads)..."
. .venv\Scripts\Activate.ps1
python cloud/run_pipeline.py --dry-run
