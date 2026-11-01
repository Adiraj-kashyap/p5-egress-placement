@echo off
call "%~dp0_env.bat" || exit /b 1
title P5 - Testbed up
echo ======================================================================
echo  BRING UP THE LOCAL KUBERNETES TESTBED  (kind, on this laptop only)
echo ======================================================================
echo  Creates the kind cluster "p5" if it is missing, loads the app images
echo  and deploys web, api, cache and db. About 3 minutes the first time.
echo  Nothing is created in any cloud.
echo ======================================================================
docker info >nul 2>&1
if errorlevel 1 goto nodocker
kubectl get nodes --request-timeout=5s >nul 2>&1
if not errorlevel 1 goto deploy
kind create cluster --name p5 --config testbed/k8s/kind.yaml
kind load docker-image p5-web:m07 p5-api:m07 --name p5
:deploy
kubectl apply -f testbed/k8s/00-namespace.yaml
kubectl apply -f testbed/k8s/
echo(
echo Waiting for pods. Press Ctrl+C once all four app pods say Running.
kubectl -n p5 get pods -w
exit /b 0

:nodocker
echo Docker is not running. Start Docker Desktop, wait for the whale icon
echo to go steady, then run this again.
pause
exit /b 1
