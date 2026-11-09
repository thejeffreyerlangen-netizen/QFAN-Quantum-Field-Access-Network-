@echo off
chcp 65001 >nul
title QFAN Client Browser
cd /d "%~dp0.."
set /p NAME="Client-Name: "
if "%NAME%"=="" set NAME=client
set /p HUB="Host-Adresse (IP[:Port], auto = LAN, leer = nur Feldordner): "
if "%HUB%"=="" (
  python -m qfan --role client --name %NAME%
) else (
  python -m qfan --role client --name %NAME% --hub %HUB%
)
pause
