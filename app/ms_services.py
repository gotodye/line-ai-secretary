"""Microsoft Graph wrappers — read Outlook / Microsoft 365 mail."""

from __future__ import annotations

import logging

import requests

from app.ms_oauth import get_access_token

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT = 20


def list_recent_outlook_emails(
    user_id: str, max_results: int = 8, unread_only: bool = True
) -> list[dict]:
    """List recent Outlook messages (unread by default).

    刻意不在 Graph 端用 $filter=isRead 搭配 $orderby——這個組合常回
    「too complex to process」。改成抓最近一批、在本地過濾未讀，穩定得多。
    """
    token = get_access_token(user_id)
    fetch = max(max_results * 3, 25) if unread_only else max_results
    resp = requests.get(
        f"{_GRAPH}/me/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "$top": fetch,
            "$select": "subject,from,receivedDateTime,isRead,bodyPreview",
            "$orderby": "receivedDateTime desc",
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        msg = body.get("error", {}).get("message") if isinstance(body, dict) else None
        raise RuntimeError(f"讀取 Outlook 失敗 (HTTP {resp.status_code}): {msg or resp.text[:120]}")

    out = []
    for m in resp.json().get("value", []):
        if unread_only and m.get("isRead"):
            continue
        sender = (m.get("from") or {}).get("emailAddress", {}) or {}
        out.append(
            {
                "from": sender.get("name") or sender.get("address") or "",
                "subject": m.get("subject") or "(無主旨)",
                "received": m.get("receivedDateTime", ""),
                "unread": not m.get("isRead", False),
                "preview": (m.get("bodyPreview") or "")[:160],
            }
        )
        if len(out) >= max_results:
            break
    return out
