"""Microsoft (Outlook / Microsoft 365) OAuth2 — 授權碼流程，讀取信件。

用 requests 手刻而非 SDK：流程單純（機密用戶端 + client_secret，不需 PKCE），
且避免再引入一個大套件。token 加密存放於 app.store，與 Google 同一把金鑰。
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

import requests

from app import config
from app import memory

logger = logging.getLogger(__name__)

_TIMEOUT = 20
# access token 過期前這段緩衝內就先刷新，避免打到一半剛好失效。
_REFRESH_SKEW = 120


class MSNotLinkedError(RuntimeError):
    pass


class MSNotConfiguredError(RuntimeError):
    pass


def _authority() -> str:
    return f"https://login.microsoftonline.com/{config.MS_TENANT_ID}/oauth2/v2.0"


def _require_configured() -> None:
    if not config.ms_oauth_configured():
        raise MSNotConfiguredError(
            "尚未設定 MS_CLIENT_ID / MS_CLIENT_SECRET / MS_TENANT_ID / MS_REDIRECT_URI"
        )


def build_auth_url(line_user_id: str) -> str:
    _require_configured()
    params = {
        "client_id": config.MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.MS_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(config.MS_SCOPES),
        # state 帶 LINE user id，callback 才知道 token 該存給誰（與 Google 一致）。
        "state": line_user_id,
        # 每次都讓使用者確認帳號，避免誤用瀏覽器已登入的另一個帳號。
        "prompt": "select_account",
    }
    return f"{_authority()}/authorize?{urlencode(params)}"


def exchange_code(code: str, state: str) -> dict:
    """Exchange auth code for tokens and store under the LINE user id (= state)."""
    _require_configured()
    resp = requests.post(
        f"{_authority()}/token",
        data={
            "client_id": config.MS_CLIENT_ID,
            "client_secret": config.MS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": config.MS_REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": " ".join(config.MS_SCOPES),
        },
        timeout=_TIMEOUT,
    )
    return _store_token_response(resp, state)


def _store_token_response(resp: requests.Response, user_id: str) -> dict:
    payload = resp.json()
    if resp.status_code >= 400 or "access_token" not in payload:
        # Microsoft 用 error / error_description 回報失敗。
        raise RuntimeError(
            payload.get("error_description")
            or payload.get("error")
            or f"Microsoft token 交換失敗 (HTTP {resp.status_code})"
        )

    token = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", " ".join(config.MS_SCOPES)),
    }
    # 刷新時 Microsoft 不一定回新的 refresh_token，沒回就沿用舊的。
    if not token["refresh_token"]:
        existing = memory.get_ms_token(user_id) or {}
        token["refresh_token"] = existing.get("refresh_token")
    memory.set_ms_token(user_id, token)
    return token


def get_access_token(user_id: str) -> str:
    """Return a valid access token, refreshing with the refresh token if needed."""
    token = memory.get_ms_token(user_id)
    if not token or not token.get("refresh_token"):
        raise MSNotLinkedError("尚未連結 Outlook，請先傳送「連結 Outlook」")

    if token.get("access_token") and time.time() < token.get("expires_at", 0) - _REFRESH_SKEW:
        return token["access_token"]

    _require_configured()
    resp = requests.post(
        f"{_authority()}/token",
        data={
            "client_id": config.MS_CLIENT_ID,
            "client_secret": config.MS_CLIENT_SECRET,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
            "scope": " ".join(config.MS_SCOPES),
        },
        timeout=_TIMEOUT,
    )
    refreshed = _store_token_response(resp, user_id)
    return refreshed["access_token"]
