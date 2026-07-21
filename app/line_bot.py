"""LINE Messaging API webhook handling."""

from __future__ import annotations

import logging
import threading

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    AudioMessageContent,
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
)

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


# 供晨間簡報等主動推播使用。
push_text = _push


def _fetch_media(message_id: str) -> bytes:
    with ApiClient(_configuration) as api_client:
        return MessagingApiBlob(api_client).get_message_content(message_id)


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(_configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )


def _process_async(
    user_id: str, text: str, attachment: tuple[bytes, str] | None = None
) -> None:
    try:
        answer = secretary.handle_text(user_id, text, attachment=attachment)
        _push(user_id, answer)
    except Exception:  # noqa: BLE001
        logger.exception("Failed handling message from %s", user_id)
        try:
            _push(user_id, "處理時發生錯誤，請稍後再試。若剛改過設定，請檢查伺服器日誌。")
        except Exception:  # noqa: BLE001
            logger.exception("Also failed to push error message")


def _ack(reply_token: str, text: str = "收到，稍等我處理…") -> None:
    try:
        _reply(reply_token, text)
    except Exception:  # noqa: BLE001
        logger.warning("Could not send quick reply ack", exc_info=True)


@handler.add(MessageEvent, message=TextMessageContent)
def on_text_message(event: MessageEvent) -> None:
    _ack(event.reply_token)
    threading.Thread(
        target=_process_async,
        args=(event.source.user_id, event.message.text),
        daemon=True,
    ).start()


def _handle_media(event: MessageEvent, mime_type: str, prompt: str, ack: str) -> None:
    _ack(event.reply_token, ack)

    def work() -> None:
        try:
            data = _fetch_media(event.message.id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed downloading media %s", event.message.id)
            _push(event.source.user_id, "檔案下載失敗，請再傳一次。")
            return
        _process_async(event.source.user_id, prompt, attachment=(data, mime_type))

    threading.Thread(target=work, daemon=True).start()


@handler.add(MessageEvent, message=ImageMessageContent)
def on_image_message(event: MessageEvent) -> None:
    _handle_media(
        event,
        mime_type="image/jpeg",
        prompt=(
            "使用者傳來這張圖片。看懂它的內容並依需要行動："
            "若是會議通知或活動海報就問要不要建立行程，"
            "若是待辦清單就問要不要加進 Google Tasks，"
            "其他情況簡短說明看到什麼。"
        ),
        ack="收到圖片，我看看…",
    )


@handler.add(MessageEvent, message=AudioMessageContent)
def on_audio_message(event: MessageEvent) -> None:
    _handle_media(
        event,
        # LINE 語音訊息是 m4a 容器。
        mime_type="audio/mp4",
        prompt=(
            "使用者傳來這段語音。聽懂內容後直接照著做，"
            "不需要先把逐字稿唸一遍。若只是閒聊就正常回應。"
        ),
        ack="收到語音，我聽聽…",
    )
