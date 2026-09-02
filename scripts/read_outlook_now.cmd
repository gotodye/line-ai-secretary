@echo off
REM 隨時手動讀 Outlook 新信（從上次讀過之後接續）並推 LINE。可直接雙擊。
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\outlook_daily.py" %*
echo.
pause
