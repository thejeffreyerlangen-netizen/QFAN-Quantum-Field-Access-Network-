@echo off
chcp 65001 >nul
title QFAN Client Browser
cd /d "%~dp0.."
set /p NAME="Client-Name: "
if "%NAME%"=="" set NAME=client
python -m qfan --role client --name %NAME% --target nexus --analyze
pause
