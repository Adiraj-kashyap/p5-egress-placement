@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 10 Test suite
echo ======================================================================
echo  10. AUTOMATED TEST SUITE  (about 4 minutes, keeps the CPU busy)
echo ======================================================================
echo  What it does : runs every pytest test: cost model, solvers agree with
echo                 the ILP, baselines, runner resume, statistics, figures,
echo                 demo chapters render, no number is typed by hand.
echo  Look for     : "N passed" at the end.
echo  Usage        : 10_tests.bat [pytest args]   e.g.  tests\test_demo.py
echo ======================================================================
"%PY%" -m pytest -q %*
call "%~dp0_pause.bat"
