@echo off
REM 由 Windows 工作排程器呼叫：切到專案根目錄、跑每日 Outlook 讀信、輸出寫進 log。
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" "scripts\outlook_daily.py" >> "logs\outlook_daily.log" 2>&1
