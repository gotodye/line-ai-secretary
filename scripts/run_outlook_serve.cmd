@echo off
REM Persistent watcher (optional alternative to the per-minute check task).
REM ASCII-only (Chinese comments break .cmd parsing).
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\pythonw.exe" "scripts\outlook_daily.py" --serve >> "logs\outlook_serve.log" 2>&1
