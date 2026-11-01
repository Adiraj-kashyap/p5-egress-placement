@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 9 Live testbed
echo ======================================================================
echo  9. LIVE TESTBED: MEASURE TRAFFIC ON KUBERNETES
echo ======================================================================
echo  What it does : checks the local kind cluster (web, api, cache, db pods),
echo                 drives it with locust for 60 s and counts the bytes on
echo                 every edge, then summarises bytes per request.
echo                 Output goes to %OUT%\testbed\, committed data untouched.
echo  Needs        : Docker Desktop running and the cluster up
echo                 (review\testbed_up.bat). Without it, the saved
echo                 measurement is shown instead.
echo ======================================================================
echo(
kubectl -n p5 get pods --request-timeout=5s 2>nul
if errorlevel 1 goto offline
echo(
"%PY%" -m testbed.measure.run_measurement --runs 1 --duration 60 --out-dir %OUT%\testbed --work-dir %OUT%\testbed\locust
if errorlevel 1 goto offline
"%PY%" -m testbed.measure.summarize --dir %OUT%\testbed
call "%~dp0_pause.bat"
exit /b 0

:offline
echo(
echo  Cluster not reachable - showing the committed measurement instead.
echo  To bring it up: start Docker Desktop, then run review\testbed_up.bat
"%PY%" -m demo.show testbed
call "%~dp0_pause.bat"
