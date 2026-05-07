$ErrorActionPreference = "Stop"

Write-Host "Telegram Ads Launcher installer"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11+ and run this script again."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment: .venv"
    python -m venv .venv
}

Write-Host "Upgrading pip"
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip

Write-Host "Installing requirements"
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "Preparing data folder"
New-Item -ItemType Directory -Force -Path "data" | Out-Null
if (-not (Test-Path "data\bots.txt")) {
    "# Add bots one per line: @bot_name or bot_name" | Set-Content -Encoding UTF8 "data\bots.txt"
}
if (-not (Test-Path "data\channel.txt")) {
    "# Add channels one per line: @channel_name or channel_name" | Set-Content -Encoding UTF8 "data\channel.txt"
}

Write-Host ""
Write-Host "Install complete"
Write-Host "Run: .\.venv\Scripts\python.exe launcher.py"
