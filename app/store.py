"""Key-value storage backend: Upstash Redis over REST, or local JSON for dev.

Render 免費方案的檔案系統是暫存的，重啟即清空，所以正式環境走 Upstash。
本機開發若未設定 Upstash，自動退回單一 JSON 檔，行為與先前相同。
"""

from __future__ import annotations

import json
import logging
import threading
import time
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


# 本機退路用來記錄各鍵到期時間的保留欄位（Redis 端由 EX 參數處理）。
_EXPIRES_FIELD = "__expires__"


def _local_expired(data: dict, key: str) -> bool:
    expires_at = data.get(_EXPIRES_FIELD, {}).get(key)
    return expires_at is not None and time.time() >= expires_at


def get(key: str) -> str | None:
    if using_remote():
        result = _command("GET", key)
        return result if isinstance(result, str) else None
    with _lock:
        data = _local_load()
        if _local_expired(data, key):
            # 到期就順手清掉，行為對齊 Redis 的 EX。
            data.pop(key, None)
            data.get(_EXPIRES_FIELD, {}).pop(key, None)
            _local_save(data)
            return None
        value = data.get(key)
    return value if isinstance(value, str) else None


def set(key: str, value: str, ttl_seconds: int | None = None) -> None:  # noqa: A001
    """Store a value, optionally expiring it after ttl_seconds."""
    if using_remote():
        if ttl_seconds:
            _command("SET", key, value, "EX", str(ttl_seconds))
        else:
            _command("SET", key, value)
        return
    with _lock:
        data = _local_load()
        data[key] = value
        expires = data.setdefault(_EXPIRES_FIELD, {})
        if ttl_seconds:
            expires[key] = time.time() + ttl_seconds
        else:
            expires.pop(key, None)
        _local_save(data)


def delete(key: str) -> None:
    if using_remote():
        _command("DEL", key)
        return
    with _lock:
        data = _local_load()
        removed = data.pop(key, None) is not None
        removed |= data.get(_EXPIRES_FIELD, {}).pop(key, None) is not None
        if removed:
            _local_save(data)


def keys(pattern: str) -> list[str]:
    """List keys matching a glob pattern (e.g. 'gtoken:*')."""
    if using_remote():
        found: list[str] = []
        cursor = "0"
        while True:
            # SCAN 而非 KEYS：KEYS 在鍵多時會阻塞 Redis。
            result = _command("SCAN", cursor, "MATCH", pattern, "COUNT", "100")
            if not isinstance(result, list) or len(result) != 2:
                break
            cursor, batch = str(result[0]), result[1]
            found.extend(k for k in (batch or []) if isinstance(k, str))
            if cursor == "0":
                break
        return found

    import fnmatch

    with _lock:
        data = _local_load()
        candidates = [k for k in data if k != _EXPIRES_FIELD]
        return [
            k
            for k in candidates
            if fnmatch.fnmatch(k, pattern) and not _local_expired(data, k)
        ]


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
