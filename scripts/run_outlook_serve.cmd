@echo off
REM 常駐看守：登入後啟動，輪詢雲端旗標；你在 LINE 傳「Outlook 信件」時觸發讀取。
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\pythonw.exe" "scripts\outlook_daily.py" --serve >> "logs\outlook_serve.log" 2>&1
