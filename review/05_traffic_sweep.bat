@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 5 Traffic sweep
echo ======================================================================
echo  5. TRAFFIC SWEEP  (hypothesis H3)
echo ======================================================================
echo  What it does : multiplies the traffic between components by s from
echo                 0.01 to 100 and solves ILP and B1 at every step, live.
echo  Look for     : the ILP stays on ONE provider at the same cost at every
echo                 s, while the B1 bill explodes because it split providers.
echo                 No crossover means H3 is refuted, and this shows why.
echo  Usage        : 05_traffic_sweep.bat [T1^|T2^|T3]   (default T2)
echo ======================================================================
set TOPO=%~1
if "%TOPO%"=="" set TOPO=T2
"%PY%" -m demo.show sweep --topology %TOPO%
call "%~dp0_pause.bat"
