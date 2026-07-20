"""Flask entrypoint: LINE webhook + Google OAuth callback."""

from __future__ import annotations

import logging
import os

from flask import Flask, abort, request
from linebot.v3.exceptions import InvalidSignatureError

from app import config
from app.google_oauth import exchange_code
from app.line_bot import handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY


@app.get("/")
def index():
    return {
        "service": "line-ai-secretary",
        "status": "ok",
        "google_oauth_configured": config.google_oauth_configured(),
        "base_url": config.BASE_URL or None,
        "webhook": "/callback",
        "oauth_callback": "/oauth/callback",
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE signature")
        abort(400)
    return "OK"


@app.get("/oauth/callback")
def oauth_callback():
    error = request.args.get("error")
    if error:
        return f"<h3>授權失敗</h3><p>{error}</p>", 400

    code = request.args.get("code")
    state = request.args.get("state")  # LINE user id
    if not code or not state:
        return "<h3>缺少 code 或 state</h3>", 400

    try:
        exchange_code(code, state)
    except Exception as e:  # noqa: BLE001
        logger.exception("OAuth exchange failed")
        return f"<h3>授權交換失敗</h3><pre>{e}</pre>", 500

    return (
        "<h2>Google 帳號已連結成功</h2>"
        "<p>可以關閉此頁，回到 LINE 跟秘書說話了。</p>"
        "<p>試試：「今天有什麼行程？」「有哪些未讀信件？」</p>"
    )


def main() -> None:
    config.require_line_config()
    if not config.google_oauth_configured():
        logger.warning(
            "Google OAuth 尚未完整設定；秘書仍可對話，但無法使用日曆／Gmail／Drive。"
        )
    port = int(os.environ.get("PORT", config.PORT))
    app.run(host=config.HOST, port=port, debug=False)


if __name__ == "__main__":
    main()
