@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed.
  pause
  exit /b 1
)
echo Installation complete. Start the client with START_CLIENT.bat.
pause
