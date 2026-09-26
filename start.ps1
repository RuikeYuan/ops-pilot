param([switch]$Live, [int]$Port = 8080)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is required.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($Live) {
    $env:OPS_DEMO = 'false'
    if (-not $env:OPS_TOKEN) { throw 'Set OPS_TOKEN to at least 24 characters for a live workspace.' }
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///data/live.db' }
} else {
    $env:OPS_DEMO = 'true'
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///data/demo.db' }
}
Write-Host "OpsPilot: http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host 'Default: local synthetic demo. Choose Explore demo workspace to enter.'
Write-Host 'Press Ctrl+C to stop.'
& .\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port $Port
