# One-command launcher for the walkthrough demo (demo/README.md has the details).
#   .\run_demo.ps1            preflight without Docker/kind, then start the app
#   .\run_demo.ps1 -Full      preflight including Docker and the kind testbed
#   .\run_demo.ps1 -Port 8600 use another port
param([switch]$Full, [int]$Port = 8501)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv found. Create it: py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r requirements.lock.txt" }

& $py -m demo.build_cache --check
if ($LASTEXITCODE -ne 0) { & $py -m demo.build_cache }

if ($Full) { & $py -m demo.preflight } else { & $py -m demo.preflight --offline }
if ($LASTEXITCODE -ne 0) { Write-Warning "Preflight reported failures; starting anyway (the testbed chapter falls back to cached measurements)." }

& ".\.venv\Scripts\streamlit.exe" run demo/app.py --server.port $Port
