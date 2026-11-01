@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 11 Walkthrough frontend
echo ======================================================================
echo  11. INTERACTIVE WALKTHROUGH IN THE BROWSER  (http://localhost:8501)
echo ======================================================================
echo  11 chapters from the problem to the conclusion, with live solving.
echo  Close this window or press Ctrl+C to stop the server.
echo ======================================================================
call "%~dp0..\run_demo.bat"
