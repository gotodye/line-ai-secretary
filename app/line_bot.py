"""LINE Messaging API webhook handling."""

from __future__ import annotations

import logging
import threading

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app import config
from app import secretary

logger = logging.getLogger(__name__)

handler = WebhookHandler(config.LINE_CHANNEL_SECRET or "placeholder")
_configuration = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN or "placeholder")


def _push(user_id: str, text: str) -> None:
    with ApiClient(_configuration) as api_client:
        api = MessagingApi(api_client)
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text[:4900])],
            )
        )


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(_configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )


def _process_async(user_id: str, text: str) -> None:
    try:
        answer = secretary.handle_text(user_id, text)
        _push(user_id, answer)
    except Exception:  # noqa: BLE001
        logger.exception("Failed handling message from %s", user_id)
        try:
            _push(user_id, "處理時發生錯誤，請稍後再試。若剛改過設定，請檢查伺服器日誌。")
        except Exception:  # noqa: BLE001
            logger.exception("Also failed to push error message")


@handler.add(MessageEvent, message=TextMessageContent)
def on_text_message(event: MessageEvent) -> None:
    user_id = event.source.user_id
    text = event.message.text
    # Quick ack so user knows we're working (optional, uses reply token once)
    try:
        _reply(event.reply_token, "收到，稍等我處理…")
    except Exception:  # noqa: BLE001
        logger.warning("Could not send quick reply ack", exc_info=True)
    threading.Thread(target=_process_async, args=(user_id, text), daemon=True).start()
