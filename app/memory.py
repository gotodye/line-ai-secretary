"""Simple JSON persistence for conversation memory and Google tokens."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

_lock = threading.Lock()


def _path(name: str) -> Path:
    return DATA_DIR / name


def _load(name: str, default: Any) -> Any:
    path = _path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save(name: str, data: Any) -> None:
    path = _path(name)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_history(user_id: str, limit: int = 12) -> list[dict[str, str]]:
    with _lock:
        store = _load("history.json", {})
        items = store.get(user_id, [])
        return items[-limit:]


def append_history(user_id: str, role: str, text: str, limit: int = 40) -> None:
    with _lock:
        store = _load("history.json", {})
        items = store.get(user_id, [])
        items.append({"role": role, "text": text})
        store[user_id] = items[-limit:]
        _save("history.json", store)


def clear_history(user_id: str) -> None:
    with _lock:
        store = _load("history.json", {})
        store.pop(user_id, None)
        _save("history.json", store)


def get_google_token(user_id: str) -> dict | None:
    with _lock:
        store = _load("google_tokens.json", {})
        return store.get(user_id)


def set_google_token(user_id: str, token_info: dict) -> None:
    with _lock:
        store = _load("google_tokens.json", {})
        store[user_id] = token_info
        _save("google_tokens.json", store)


def delete_google_token(user_id: str) -> None:
    with _lock:
        store = _load("google_tokens.json", {})
        store.pop(user_id, None)
        _save("google_tokens.json", store)


def is_google_linked(user_id: str) -> bool:
    token = get_google_token(user_id)
    return bool(token and (token.get("refresh_token") or token.get("token")))
