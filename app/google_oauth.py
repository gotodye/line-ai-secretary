"""Google OAuth2 helpers for linking a LINE user to Google services."""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app import config
from app import memory


class GoogleNotLinkedError(RuntimeError):
    pass


class GoogleNotConfiguredError(RuntimeError):
    pass


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
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def exchange_code(code: str, state: str) -> dict:
    """Exchange auth code for tokens and store under LINE user id (= state)."""
    flow = Flow.from_client_config(
        _client_config(),
        scopes=config.GOOGLE_SCOPES,
        state=state,
    )
    flow.redirect_uri = config.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
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
