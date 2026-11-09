@echo off
chcp 65001 >nul
title QFAN Server · Nexus
cd /d "%~dp0.."
python -c "import numpy" 2>nul || python -m pip install -r requirements.txt
python -m qfan --role host --name nexus --analyze
pause
