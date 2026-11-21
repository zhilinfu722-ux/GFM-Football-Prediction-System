@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo   GFM Football Prediction System
 echo   Local launcher
 echo ==========================================
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ was not found. Install Python from https://www.python.org/downloads/
    echo During setup, enable "Add Python to PATH".
    pause
    exit /b 1
  )
  set PY=python
) else (
  set PY=py -3
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 goto failed
)
echo Checking dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Starting GFM in your browser...
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. Check Python installation and internet connection.
pause
exit /b 1
