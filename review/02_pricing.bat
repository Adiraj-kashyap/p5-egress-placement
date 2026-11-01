@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - 2 Cloud price snapshot
echo ======================================================================
echo  2. CLOUD PRICE SNAPSHOT  (objective O1)
echo ======================================================================
echo  What it does : reads the committed AWS / Azure / GCP price tables
echo                 (pulled from the public price lists, no cloud account,
echo                 nothing provisioned) and the 10 validation checks.
echo  Look for     : compute is cheapest in aws:us-east-1 / azure:eastus;
echo                 same-region traffic is free, cross-provider traffic is
echo                 billed at the internet rate (rule R3); 10/10 checks PASS.
echo ======================================================================
"%PY%" -m demo.show pricing
call "%~dp0_pause.bat"
