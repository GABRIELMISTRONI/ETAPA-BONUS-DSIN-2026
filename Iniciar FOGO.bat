@echo off
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3.10+ nao foi encontrado. Instale Python e marque a opcao para adicionar ao PATH.
  pause
  exit /b 1
)
start "F.O.G.O. API" cmd /k ""%PY%" server.py"
timeout /t 2 /nobreak >nul
start "F.O.G.O. Simulador IoT" cmd /k ""%PY%" simulador.py --interval 25"
start "" http://127.0.0.1:8000
