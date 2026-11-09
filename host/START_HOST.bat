@echo off
chcp 65001 >nul
title QFAN Host - Nexus
cd /d "%~dp0.."
python -m qfan --role host --name nexus --analyze
pause
