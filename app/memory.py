"""Conversation memory and Google tokens, persisted via app.store."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app import crypto
from app import store

logger = logging.getLogger(__name__)

# 單一 gunicorn worker 下足以避免同一使用者的讀改寫互相覆蓋。
_lock = threading.Lock()


def _history_key(user_id: str) -> str:
    return f"history:{user_id}"


def _token_key(user_id: str) -> str:
    return f"gtoken:{user_id}"


def _load_history(user_id: str) -> list[dict[str, str]]:
    raw = store.get(_history_key(user_id))
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("對話記憶格式毀損，重置: %s", user_id)
        return []
    return items if isinstance(items, list) else []


def get_history(user_id: str, limit: int = 12) -> list[dict[str, str]]:
    try:
        return _load_history(user_id)[-limit:]
    except store.StoreError as exc:
        # 記憶讀不到不該讓對話中斷，退化成無上下文繼續回答。
        logger.error("讀取對話記憶失敗: %s", exc)
        return []


def append_history(user_id: str, role: str, text: str, limit: int = 40) -> None:
    try:
        with _lock:
            items = _load_history(user_id)
            items.append({"role": role, "text": text})
            store.set(
                _history_key(user_id),
                json.dumps(items[-limit:], ensure_ascii=False),
            )
    except store.StoreError as exc:
        logger.error("寫入對話記憶失敗: %s", exc)


def clear_history(user_id: str) -> None:
    try:
        store.delete(_history_key(user_id))
    except store.StoreError as exc:
        logger.error("清除對話記憶失敗: %s", exc)


def get_google_token(user_id: str) -> dict | None:
    """Token 讀寫失敗一律往上拋 — 靜默失敗會讓使用者以為授權還在。"""
    raw = store.get(_token_key(user_id))
    if not raw:
        return None
    decrypted = crypto.decrypt(raw)
    try:
        token = json.loads(decrypted)
    except json.JSONDecodeError:
        logger.error("Google token 格式毀損: %s", user_id)
        return None
    return token if isinstance(token, dict) else None


def set_google_token(user_id: str, token_info: dict[str, Any]) -> None:
    payload = json.dumps(token_info, ensure_ascii=False)
    store.set(_token_key(user_id), crypto.encrypt(payload))


def delete_google_token(user_id: str) -> None:
    store.delete(_token_key(user_id))


def is_google_linked(user_id: str) -> bool:
    try:
        token = get_google_token(user_id)
    except (store.StoreError, RuntimeError) as exc:
        logger.error("查詢 Google 連結狀態失敗: %s", exc)
        return False
    return bool(token and (token.get("refresh_token") or token.get("token")))
