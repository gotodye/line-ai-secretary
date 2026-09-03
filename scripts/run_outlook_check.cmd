@echo off
REM Called every minute by the scheduler: checks the cloud flag; only reads Outlook
REM when you send an "Outlook" message in LINE. ASCII-only (Chinese breaks .cmd parsing).
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" "scripts\outlook_daily.py" --check >> "logs\outlook_check.log" 2>&1
