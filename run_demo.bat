@echo off
rem Double-click launcher for the walkthrough demo. Same steps as run_demo.ps1.
rem   run_demo.bat           offline preflight, then the app on http://localhost:8501
rem   run_demo.bat full      include the Docker/kind checks
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No .venv found. Create it: py -3.12 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.lock.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m demo.build_cache --check || ".venv\Scripts\python.exe" -m demo.build_cache
if /i "%1"=="full" (
  ".venv\Scripts\python.exe" -m demo.preflight
) else (
  ".venv\Scripts\python.exe" -m demo.preflight --offline
)
if errorlevel 1 echo WARNING: preflight reported failures; starting anyway (the testbed chapter falls back to cached measurements).
".venv\Scripts\streamlit.exe" run demo/app.py
