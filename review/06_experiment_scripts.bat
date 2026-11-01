@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 6 Experiment scripts
echo ======================================================================
echo  6. THE EXPERIMENT SCRIPTS THEMSELVES  (baselines, exact ILP, heuristics)
echo ======================================================================
echo  What it does : runs the same scripts that produced the reported results
echo                 on T1-T3. Output goes to %OUT%\ so the committed
echo                 results folder is never touched.
echo  Look for     : B1 vs B2-best per topology; both ILP formulations agree
echo                 and are proven optimal in well under a second; the
echo                 greedy gap to the ILP optimum in percent.
echo ======================================================================
echo(
echo ---- 6a. Baselines: B1 cheapest compute, egress-blind; B2 one provider
"%PY%" -m experiments.run_baselines --out %OUT%\baselines
call "%~dp0_pause.bat"
echo ---- 6b. Exact ILP with CBC, tight and McCormick formulations
"%PY%" -m experiments.run_exact --repeats 1 --out %OUT%\exact
call "%~dp0_pause.bat"
echo ---- 6c. Greedy and greedy+1-opt, with the gap to the ILP optimum
"%PY%" -m experiments.run_heuristics --repeats 1 --out %OUT%\heuristics
call "%~dp0_pause.bat"
