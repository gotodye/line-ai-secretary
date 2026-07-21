"""Symmetric encryption for Google tokens at rest."""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app import config

logger = logging.getLogger(__name__)

_ENCRYPTED_PREFIX = "enc:"


def _fernet() -> Fernet | None:
    if not config.TOKEN_ENCRYPTION_KEY:
        return None
    try:
        return Fernet(config.TOKEN_ENCRYPTION_KEY.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY 不是有效的 Fernet 金鑰，"
            "請以 scripts/generate_keys.ps1 重新產生"
        ) from exc


def encrypt(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        return plaintext
    return _ENCRYPTED_PREFIX + f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    """Decrypt a stored value; passes through values written before encryption."""
    if not value.startswith(_ENCRYPTED_PREFIX):
        # 舊資料是明文，直接回傳；下次寫入時就會被加密。
        return value

    f = _fernet()
    if f is None:
        raise RuntimeError(
            "儲存的 token 已加密，但 TOKEN_ENCRYPTION_KEY 未設定，無法解密"
        )
    try:
        return f.decrypt(value[len(_ENCRYPTED_PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "token 解密失敗，TOKEN_ENCRYPTION_KEY 可能已更換；"
            "受影響的使用者需要重新連結 Google"
        ) from exc
