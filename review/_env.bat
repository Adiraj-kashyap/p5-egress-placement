@echo off
rem Shared setup for every review\*.bat: repo root, UTF-8 console, venv python, local tool paths.
cd /d "%~dp0.."
chcp 65001 >nul
set PYTHONUTF8=1
set PY=.venv\Scripts\python.exe
set OUT=logs\review_runs
set PATH=%CD%\.tools\bin;%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%ProgramFiles%\Docker\Docker\resources\bin;%PATH%
set KUBECONFIG=%CD%\.tools\kube\config
if not exist "%PY%" (
  echo No .venv found. Create it first: py -3.12 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.lock.txt
  pause
  exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"
exit /b 0
