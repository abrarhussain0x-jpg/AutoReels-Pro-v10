# Setup development environment (Windows PowerShell)
param()

Write-Host "Creating virtualenv and installing Python dependencies..."
python -m venv .venv
. .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r cloud/requirements.txt
Write-Host "Done. Activate with: . .venv\Scripts\Activate.ps1"
