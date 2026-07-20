@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if not exist .env (
  copy .env.example .env
  echo.
  echo 已建立 .env，請先填入 LINE / Gemini / Google 金鑰後再執行。
  pause
  exit /b 1
)
python -m app.main
