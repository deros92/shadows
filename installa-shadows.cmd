@echo off
rem Registra Shadows presso Chrome ed Edge (una volta sola). Doppio clic.
rem Da quel momento e' il browser ad avviare Shadows: nessuna finestra, nessuna porta.
rem Interprete: SHADOWS_PYTHON se impostata, altrimenti la .venv del progetto se esiste,
rem altrimenti il python del PATH. Il browser usera' lo stesso interprete.
title Installazione di Shadows
cd /d "%~dp0"
if "%SHADOWS_PYTHON%"=="" if exist "%~dp0.venv\Scripts\python.exe" set "SHADOWS_PYTHON=%~dp0.venv\Scripts\python.exe"
if "%SHADOWS_PYTHON%"=="" set "SHADOWS_PYTHON=python"
"%SHADOWS_PYTHON%" -c "import shadows.server, transformers" 2>nul
if errorlevel 1 (
  echo Python non trovato o dipendenze mancanti con: %SHADOWS_PYTHON%
  echo Crea l'ambiente del progetto con:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
  echo   .venv\Scripts\pip install -r requirements.txt
  echo oppure imposta SHADOWS_PYTHON con il percorso di un python.exe gia' pronto.
  pause
  exit /b 1
)
"%SHADOWS_PYTHON%" -m shadows install-native
echo.
echo Fatto. Se il modello non e' ancora stato scaricato, al primo uso servira' qualche minuto.
pause
