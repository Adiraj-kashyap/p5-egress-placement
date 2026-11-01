@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 1 Environment and solver check
echo ======================================================================
echo  1. ENVIRONMENT AND SOLVER CHECK
echo ======================================================================
echo  What it does : prints Python, OS, git commit and the installed solver,
echo                 then solves a tiny 3-component placement with CBC.
echo  Look for     : "status: Optimal", the egress-aware optimum beating the
echo                 egress-blind greedy, and "ENVIRONMENT OK" at the end.
echo ======================================================================
echo(
"%PY%" verify_env.py
call "%~dp0_pause.bat"
