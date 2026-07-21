"""Google OAuth2 helpers for linking a LINE user to Google services."""

from __future__ import annotations

import os

# Google 回傳的 scope 常與請求時不完全一致：openid 會被補上 userinfo 相關項目，
# include_granted_scopes 也會把先前已授權的 scope 一併帶回來。oauthlib 預設會把
# 這種差異當成錯誤直接擋下（Scope has changed from ... to ...），導致換 token 失敗。
# 必須在 import oauthlib 之前設定才有效。
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import Flow  # noqa: E402

from app import config  # noqa: E402
from app import memory  # noqa: E402
from app import store  # noqa: E402

# 授權連結與 callback 是兩個獨立的請求（甚至可能是不同的行程），
# PKCE 的 code_verifier 必須跨請求保存，否則換 token 會被 Google 以
# 「Missing code verifier」拒絕。授權通常幾分鐘內完成，給 10 分鐘足夠。
_PKCE_TTL_SECONDS = 600


class GoogleNotLinkedError(RuntimeError):
    pass


class GoogleNotConfiguredError(RuntimeError):
    pass


def _pkce_key(state: str) -> str:
    return f"pkce:{state}"


def _client_config() -> dict:
    if not config.google_oauth_configured():
        raise GoogleNotConfiguredError(
            "尚未設定 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI"
        )
    return {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config.GOOGLE_REDIRECT_URI],
        }
    }


def build_auth_url(line_user_id: str) -> str:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=config.GOOGLE_SCOPES,
        state=line_user_id,
    )
    flow.redirect_uri = config.GOOGLE_REDIRECT_URI
    # authorization_url() 會在這裡才產生 code_verifier 並送出對應的 challenge，
    # 所以要在呼叫之後才讀得到。
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if flow.code_verifier:
        store.set(
            _pkce_key(line_user_id), flow.code_verifier, ttl_seconds=_PKCE_TTL_SECONDS
        )
    return auth_url


def exchange_code(code: str, state: str) -> dict:
    """Exchange auth code for tokens and store under LINE user id (= state)."""
    code_verifier = store.get(_pkce_key(state))
    if not code_verifier:
        # 超過 10 分鐘才點連結、或伺服器換過儲存設定都會走到這裡。
        raise RuntimeError(
            "授權連結已逾時或失效，請回到 LINE 重新傳送「連結 Google」取得新連結"
        )

    flow = Flow.from_client_config(
        _client_config(),
        scopes=config.GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = config.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    # 一次性使用，換完就清掉。
    store.delete(_pkce_key(state))
    creds = flow.credentials
    token_info = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or config.GOOGLE_SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    # Keep previous refresh_token if Google does not return a new one
    existing = memory.get_google_token(state) or {}
    if not token_info.get("refresh_token") and existing.get("refresh_token"):
        token_info["refresh_token"] = existing["refresh_token"]
    memory.set_google_token(state, token_info)
    return token_info


def get_credentials(user_id: str) -> Credentials:
    token_info = memory.get_google_token(user_id)
    if not token_info:
        raise GoogleNotLinkedError("尚未連結 Google 帳號，請先傳送「連結 Google」")

    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_info.get("client_id") or config.GOOGLE_CLIENT_ID,
        client_secret=token_info.get("client_secret") or config.GOOGLE_CLIENT_SECRET,
        scopes=token_info.get("scopes") or config.GOOGLE_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        memory.set_google_token(
            user_id,
            {
                **token_info,
                "token": creds.token,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
                "scopes": list(creds.scopes or token_info.get("scopes") or []),
            },
        )
    return creds
