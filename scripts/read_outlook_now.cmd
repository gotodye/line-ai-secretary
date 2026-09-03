@echo off
REM Manual on-demand read of new Outlook mail (continues from last read), push to LINE.
REM Double-click to run. ASCII-only (Chinese comments break .cmd parsing).
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\outlook_daily.py" %*
echo.
pause
