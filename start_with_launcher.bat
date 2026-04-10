@echo off
cd /d "%~dp0"

python download_launcher.py
if errorlevel 1 (
  echo Launcher setup failed.
  pause
  exit /b 1
)

python server_bot_all_in_one.py
