@echo off
rem Pause between screens unless RUN_ALL asked for no pauses.
if defined P5_NO_PAUSE exit /b 0
echo(
pause
