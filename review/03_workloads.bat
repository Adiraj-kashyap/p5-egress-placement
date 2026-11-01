@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 3 Workloads and measured traffic
echo ======================================================================
echo  3. WORKLOADS T1-T3 AND MEASURED TRAFFIC
echo ======================================================================
echo  What it does : prints the three application graphs (components with
echo                 vCPU and storage, edges with GB per month), then the
echo                 bytes per request measured on the Kubernetes testbed
echo                 that T1's volumes come from.
echo  Look for     : T1 volumes are measured, not assumed; cv_pct under 1
echo                 means the measurement is repeatable.
echo ======================================================================
"%PY%" -m demo.show workloads
"%PY%" -m demo.show testbed
call "%~dp0_pause.bat"
