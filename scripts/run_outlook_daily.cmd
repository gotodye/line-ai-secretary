@echo off
REM Called by the daily 07:00 scheduler: read new Outlook mail and push to LINE.
REM ASCII-only (Chinese comments break .cmd parsing).
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" "scripts\outlook_daily.py" >> "logs\outlook_daily.log" 2>&1
