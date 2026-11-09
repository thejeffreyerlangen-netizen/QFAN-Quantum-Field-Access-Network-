@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --name QFAN-Host -p . run_host.py
pyinstaller --noconsole --onefile --name QFAN-Client -p . run_client.py
echo Fertig: dist\QFAN-Host.exe und dist\QFAN-Client.exe
pause
