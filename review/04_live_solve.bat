@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 4 Live solve
echo ======================================================================
echo  4. LIVE SOLVE: EXACT ILP vs HEURISTICS vs EGRESS-BLIND BASELINE
echo ======================================================================
echo  What it does : builds the placement problem from the prices and the
echo                 workload, then solves it right now with the ILP (CBC),
echo                 simulated annealing, greedy+1-opt, and baselines B1 and
echo                 B2. Every bill is computed by the same cost function.
echo  Look for     : ILP "proven optimal"; how much more B1 pays (penalty);
echo                 B1 splits components across providers and pays egress.
echo  Usage        : 04_live_solve.bat [T1^|T2^|T3] [scale]   e.g.  T2 100
echo ======================================================================
set TOPO=%~1
set SCALE=%~2
if "%TOPO%"=="" if not defined P5_NO_PAUSE set /p TOPO=Workload T1, T2 or T3 [Enter = T1]:
if "%TOPO%"=="" set TOPO=T1
if "%SCALE%"=="" if not defined P5_NO_PAUSE set /p SCALE=Traffic scale s, e.g. 1 or 100 [Enter = 1]:
if "%SCALE%"=="" set SCALE=1
"%PY%" -m demo.show solve --topology %TOPO% --scale %SCALE%
call "%~dp0_pause.bat"
