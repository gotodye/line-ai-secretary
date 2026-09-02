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


def _ms_token_key(user_id: str) -> str:
    return f"mstoken:{user_id}"


def _facts_key(user_id: str) -> str:
    return f"facts:{user_id}"


# 事實是長期記憶，不像對話記憶會滾動淘汰，所以設上限避免無限成長
# 撐爆 system prompt。
MAX_FACTS = 60


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


def get_full_history(user_id: str) -> list[dict[str, str]]:
    """Whole stored history. Callers that will also append should use this and
    hand the result back to append_exchange, so one turn costs one read."""
    try:
        return _load_history(user_id)
    except store.StoreError as exc:
        # 記憶讀不到不該讓對話中斷，退化成無上下文繼續回答。
        logger.error("讀取對話記憶失敗: %s", exc)
        return []


def get_history(user_id: str, limit: int = 12) -> list[dict[str, str]]:
    return get_full_history(user_id)[-limit:]


def append_exchange(
    user_id: str,
    user_text: str,
    answer: str,
    known_full: list[dict[str, str]] | None = None,
    limit: int = 40,
) -> None:
    """Append both sides of one turn in a single write.

    分兩次呼叫 append_history 會產生四次 Upstash 往返（各一讀一寫）；
    跨區域時每次約 160 ms，光這裡就是半秒。傳入 known_full 可再省掉一次讀取。
    """
    try:
        with _lock:
            items = known_full if known_full is not None else _load_history(user_id)
            items = [*items, {"role": "user", "text": user_text},
                     {"role": "assistant", "text": answer}]
            store.set(
                _history_key(user_id), json.dumps(items[-limit:], ensure_ascii=False)
            )
    except store.StoreError as exc:
        logger.error("寫入對話記憶失敗: %s", exc)


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


def get_ms_token(user_id: str) -> dict | None:
    """Microsoft (Outlook) token，加密存放，讀寫失敗往上拋。"""
    raw = store.get(_ms_token_key(user_id))
    if not raw:
        return None
    try:
        token = json.loads(crypto.decrypt(raw))
    except json.JSONDecodeError:
        logger.error("Microsoft token 格式毀損: %s", user_id)
        return None
    return token if isinstance(token, dict) else None


def set_ms_token(user_id: str, token_info: dict[str, Any]) -> None:
    store.set(_ms_token_key(user_id), crypto.encrypt(json.dumps(token_info, ensure_ascii=False)))


def delete_ms_token(user_id: str) -> None:
    store.delete(_ms_token_key(user_id))


def is_ms_linked(user_id: str) -> bool:
    try:
        token = get_ms_token(user_id)
    except (store.StoreError, RuntimeError) as exc:
        logger.error("查詢 Outlook 連結狀態失敗: %s", exc)
        return False
    return bool(token and token.get("refresh_token"))


def get_facts(user_id: str) -> list[str]:
    """Long-term facts the user asked the secretary to remember."""
    try:
        raw = store.get(_facts_key(user_id))
    except store.StoreError as exc:
        logger.error("讀取長期記憶失敗: %s", exc)
        return []
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("長期記憶格式毀損，重置: %s", user_id)
        return []
    return [f for f in items if isinstance(f, str)] if isinstance(items, list) else []


def add_fact(user_id: str, fact: str) -> str:
    fact = fact.strip()
    if not fact:
        return "沒有可記住的內容。"
    with _lock:
        facts = get_facts(user_id)
        # 完全相同的敘述不重複記錄；語意重複交給模型自己判斷。
        if fact in facts:
            return f"這件事我已經記住了：{fact}"
        facts.append(fact)
        dropped = ""
        if len(facts) > MAX_FACTS:
            removed = facts.pop(0)
            dropped = f"（記憶已滿，忘掉最舊的一則：{removed}）"
        store.set(_facts_key(user_id), json.dumps(facts, ensure_ascii=False))
    return f"記住了：{fact}{dropped}"


def remove_fact(user_id: str, keyword: str) -> str:
    keyword = keyword.strip()
    if not keyword:
        return "請說明要忘記什麼。"
    with _lock:
        facts = get_facts(user_id)
        matched = [f for f in facts if keyword in f]
        if not matched:
            return f"沒有找到跟「{keyword}」有關的記憶。"
        kept = [f for f in facts if f not in matched]
        store.set(_facts_key(user_id), json.dumps(kept, ensure_ascii=False))
    return "已忘記：" + "、".join(matched)


def clear_facts(user_id: str) -> None:
    try:
        store.delete(_facts_key(user_id))
    except store.StoreError as exc:
        logger.error("清除長期記憶失敗: %s", exc)


def list_linked_users() -> list[str]:
    """LINE user ids that have a stored Google token — the brief's audience."""
    try:
        return [k.split(":", 1)[1] for k in store.keys("gtoken:*") if ":" in k]
    except store.StoreError as exc:
        logger.error("列舉已連結使用者失敗: %s", exc)
        return []


def get_brief_sent_date(user_id: str) -> str | None:
    """The date (Taipei) the morning brief was last delivered to this user."""
    try:
        return store.get(f"briefed:{user_id}")
    except store.StoreError as exc:
        logger.error("讀取簡報寄送紀錄失敗: %s", exc)
        # 讀不到時當作「尚未寄送」——寧可重寄，也不要漏寄。
        return None


def mark_brief_sent(user_id: str, date_str: str) -> None:
    try:
        # 兩天後自動過期，避免使用者解除連結後殘留鍵；每天照樣會被新日期覆蓋。
        store.set(f"briefed:{user_id}", date_str, ttl_seconds=172800)
    except store.StoreError as exc:
        logger.error("寫入簡報寄送紀錄失敗: %s", exc)


def is_google_linked(user_id: str) -> bool:
    try:
        token = get_google_token(user_id)
    except (store.StoreError, RuntimeError) as exc:
        logger.error("查詢 Google 連結狀態失敗: %s", exc)
        return False
    return bool(token and (token.get("refresh_token") or token.get("token")))
