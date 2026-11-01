@echo off
rem Runs every review screen in order (review\01 ... review\10), then opens the
rem browser walkthrough. Each screen explains what it does and waits for a key.
rem   RUN_ALL.bat           presenter mode: pause after every screen
rem   RUN_ALL.bat nopause   run straight through (rehearsal / sanity check)
cd /d "%~dp0"
if /i "%~1"=="nopause" set P5_NO_PAUSE=1

call review\01_environment.bat
call review\02_pricing.bat
call review\03_workloads.bat
call review\04_live_solve.bat T1 1
call review\04_live_solve.bat T2 1
call review\05_traffic_sweep.bat T2
call review\06_experiment_scripts.bat
call review\07_experiment_runner.bat
call review\08_results_and_verdicts.bat
call review\09_testbed_live.bat

if defined P5_NO_PAUSE goto frontend
choice /c YN /n /m "Run the full test suite now (about 4 minutes)? [Y/N] "
if errorlevel 2 goto frontend
call review\10_tests.bat

:frontend
call review\11_frontend.bat
