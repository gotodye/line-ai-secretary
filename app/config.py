"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
# 僅在未設定外部儲存時當作退路使用；目錄由 app.store 需要時才建立，
# 避免用了 Upstash 還在唯讀路徑上 mkdir 導致開機失敗。
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR / "data")))

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    f"{BASE_URL}/oauth/callback" if BASE_URL else "",
).strip()

FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# 外部儲存（Upstash Redis REST）。兩者皆未設定時退回本機 JSON 檔，供本地開發用。
# Render 免費方案沒有持久磁碟，正式環境一定要設，否則重啟即遺失所有授權。
UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
# Fernet 金鑰，用來加密存放的 Google token。以 scripts/generate_keys.ps1 產生。
TOKEN_ENCRYPTION_KEY = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()

# Google OAuth scopes for secretary features
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/spreadsheets",
]


def require_line_config() -> None:
    missing = []
    if not LINE_CHANNEL_SECRET:
        missing.append("LINE_CHANNEL_SECRET")
    if not LINE_CHANNEL_ACCESS_TOKEN:
        missing.append("LINE_CHANNEL_ACCESS_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        raise RuntimeError(f"缺少必要環境變數: {', '.join(missing)}")


def google_oauth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def remote_store_configured() -> bool:
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def require_store_config() -> None:
    """外部儲存只設一半，或設了卻沒金鑰，都在啟動時擋下來。"""
    if bool(UPSTASH_REDIS_REST_URL) != bool(UPSTASH_REDIS_REST_TOKEN):
        raise RuntimeError(
            "UPSTASH_REDIS_REST_URL 與 UPSTASH_REDIS_REST_TOKEN 必須同時設定"
        )
    if remote_store_configured() and not TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "使用外部儲存時必須設定 TOKEN_ENCRYPTION_KEY，"
            "否則 Google token 會以明文存在外部服務。"
            "產生金鑰：pwsh scripts/generate_keys.ps1"
        )
