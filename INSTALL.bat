@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python -m pip install -r requirements.txt
echo OK — weiter mit START_CLIENT.bat
pause
