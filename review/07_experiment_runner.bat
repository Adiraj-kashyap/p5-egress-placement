@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 7 Experiment runner
echo ======================================================================
echo  7. EXPERIMENT RUNNER  (smoke grid, about 20 seconds)
echo ======================================================================
echo  What it does : the resumable runner that executed every experiment
echo                 (16,000+ jobs). Here it runs the small "smoke" grid:
echo                 synthetic workloads of 6 and 12 components x all 7
echo                 methods, one row per job into %OUT%\smoke\.
echo  Look for     : jobs ticking by, then the per-method summary with status
echo                 optimal / ok and the run time of each method.
echo ======================================================================
if exist %OUT%\smoke rmdir /s /q %OUT%\smoke
"%PY%" -m experiments.runner smoke --out %OUT%\smoke --allow-dirty
call "%~dp0_pause.bat"
