"""Key-value storage backend: Upstash Redis over REST, or local JSON for dev.

Render 免費方案的檔案系統是暫存的，重啟即清空，所以正式環境走 Upstash。
本機開發若未設定 Upstash，自動退回單一 JSON 檔，行為與先前相同。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import requests

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_LOCAL_FILE = "store.json"
_TIMEOUT = 10


class StoreError(RuntimeError):
    pass


def using_remote() -> bool:
    return config.remote_store_configured()


def _command(*args: str) -> object:
    """Run a Redis command through the Upstash REST endpoint."""
    try:
        resp = requests.post(
            config.UPSTASH_REDIS_REST_URL,
            headers={"Authorization": f"Bearer {config.UPSTASH_REDIS_REST_TOKEN}"},
            json=[str(a) for a in args],
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StoreError(f"連線 Upstash 失敗（{args[0]}）: {exc}") from exc

    if resp.status_code >= 400:
        raise StoreError(f"Upstash {args[0]} 回應 HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise StoreError(f"Upstash {args[0]} 回應非 JSON") from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise StoreError(f"Upstash {args[0]} 失敗: {payload['error']}")
    return payload.get("result") if isinstance(payload, dict) else None


def _local_path() -> Path:
    data_dir = Path(config.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / _LOCAL_FILE


def _local_load() -> dict:
    path = _local_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("本機儲存檔毀損，重新開始: %s", path)
        return {}


def _local_save(data: dict) -> None:
    _local_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get(key: str) -> str | None:
    if using_remote():
        result = _command("GET", key)
        return result if isinstance(result, str) else None
    with _lock:
        value = _local_load().get(key)
    return value if isinstance(value, str) else None


def set(key: str, value: str) -> None:  # noqa: A001 - mirrors the Redis verb
    if using_remote():
        _command("SET", key, value)
        return
    with _lock:
        data = _local_load()
        data[key] = value
        _local_save(data)


def delete(key: str) -> None:
    if using_remote():
        _command("DEL", key)
        return
    with _lock:
        data = _local_load()
        if data.pop(key, None) is not None:
            _local_save(data)


def healthy() -> bool:
    """Used at startup to fail loudly rather than on the first user message."""
    if not using_remote():
        return True
    try:
        _command("PING")
        return True
    except StoreError as exc:
        logger.error("外部儲存無法連線: %s", exc)
        return False
