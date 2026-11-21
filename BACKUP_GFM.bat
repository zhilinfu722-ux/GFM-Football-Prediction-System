@echo off
cd /d "%~dp0"
if not exist data mkdir data
if exist data\gfm.db (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set stamp=%%i
  copy /Y data\gfm.db data\gfm_backup_%stamp%.db >nul
  echo Backup saved to data\gfm_backup_%stamp%.db
) else (
  echo Database not found yet. Start GFM once to create it.
)
pause
