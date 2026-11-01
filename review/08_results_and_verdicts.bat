@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 8 Results and verdicts
echo ======================================================================
echo  8. RESULTS, REPRODUCIBILITY CHECKS AND HYPOTHESIS VERDICTS
echo ======================================================================
echo  What it does : a. checks every reported configuration was repeated,
echo                    n of at least 3
echo                 b. regenerates the verdicts and report tables from the
echo                    raw runs and checks they match the committed ones
echo                 c. checks every number in the results text is in a table
echo                 d. prints the pre-registered hypotheses and verdicts
echo  Look for     : PASS / OK on every check, then H1-H3 with CIs and p-values.
echo ======================================================================
echo(
echo ---- 8a. Replication guard
"%PY%" -m experiments.check_replication
echo(
echo ---- 8b. Verdicts and tables regenerate identically from raw results
"%PY%" -m analysis.verdicts --check
"%PY%" -m analysis.tables --check
echo(
echo ---- 8c. No untraceable numbers in the results text
"%PY%" -m analysis.check_numbers
call "%~dp0_pause.bat"
echo ---- 8d. Hypotheses and verdicts
"%PY%" -m demo.show verdicts
call "%~dp0_pause.bat"
