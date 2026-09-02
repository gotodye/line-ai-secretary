"""Flask entrypoint: LINE webhook + Google OAuth callback."""

from __future__ import annotations

import hmac
import logging
import os
import threading

from flask import Flask, abort, request
from linebot.v3.exceptions import InvalidSignatureError

from app import briefing
from app import config
from app import store
from app.google_oauth import exchange_code
from app.line_bot import handler, push_text
from app.ms_oauth import exchange_code as ms_exchange_code

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 在 import 時就驗證，讓設定錯誤直接讓 gunicorn 開機失敗、部署顯示紅燈，
# 而不是等到第一個使用者訊息才炸。main() 在 gunicorn 下不會被呼叫。
config.require_store_config()
if not config.remote_store_configured():
    logger.warning(
        "未設定外部儲存，資料寫在本機檔案。"
        "Render 免費方案重啟即清空，正式環境請設定 UPSTASH_REDIS_REST_URL / TOKEN。"
    )
elif not store.healthy():
    logger.error("外部儲存連線失敗，Google 授權與對話記憶將無法保存")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY


@app.get("/")
def index():
    return {
        "service": "line-ai-secretary",
        "status": "ok",
        "google_oauth_configured": config.google_oauth_configured(),
        "ms_oauth_configured": config.ms_oauth_configured(),
        "base_url": config.BASE_URL or None,
        "storage": "upstash-redis" if config.remote_store_configured() else "local-file",
        "webhook": "/callback",
        "oauth_callback": "/oauth/callback",
        "ms_oauth_callback": "/oauth/ms/callback",
    }


@app.get("/health")
def health():
    # 保持零外部呼叫：這支被 Render 高頻輪詢，每次都 PING Upstash 會吃光免費額度。
    # 要檢查儲存連線請用 /health?deep=1。
    if request.args.get("deep"):
        return {"ok": True, "storage_ok": store.healthy()}
    return {"ok": True}


@app.get("/ping")
def ping():
    # 專供 keep-alive 排程使用：回傳完全空的 204。
    # 某些排程服務（如 cron-job.org）的抓取器對經 Cloudflare 的 chunked 回應
    # 會誤判「output too large」——即使 body 只有十幾個位元組。零 body 讓這個
    # 判斷無從成立，喚醒服務只需要一個 2xx 就夠了。
    return "", 204


@app.post("/cron/brief")
@app.get("/cron/brief")
def cron_brief():
    """Triggered by an external scheduler to push the morning brief."""
    if not config.CRON_SECRET:
        logger.warning("收到晨間簡報請求，但未設定 CRON_SECRET")
        return {"error": "尚未設定 CRON_SECRET"}, 503

    supplied = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    # 固定時間比較，避免以回應時間逐字元猜出密碼。
    if not hmac.compare_digest(supplied, config.CRON_SECRET):
        logger.warning("晨間簡報請求的密碼不正確")
        return {"error": "unauthorized"}, 401

    # 一位使用者的簡報要跑 20 秒以上（多次 Gemini 呼叫加工具查詢），多位使用者
    # 就是好幾十秒；排程服務的請求逾時通常只有 30 秒，同步處理必定被中斷。
    # 立刻回應、背景執行，簡報本來就是靠推播送達，不需要留在這個連線裡。
    # force=1 略過「今天已寄」檢查，供手動測試用；排程觸發不帶，維持冪等。
    force = (request.args.get("force") or "").lower() in ("1", "true", "yes")

    def work() -> None:
        try:
            logger.info("晨間簡報開始")
            result = briefing.send_briefs(push_text, force=force)
            logger.info("晨間簡報結果: %s", result)
        except Exception:  # noqa: BLE001
            logger.exception("晨間簡報執行失敗")

    threading.Thread(target=work, daemon=True).start()
    # 空 body：與 /ping 同理，避免排程服務誤判回應過大。
    return "", 202


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
    except Exception:  # noqa: BLE001
        # 細節只寫進 log，不回傳給終端使用者
        logger.exception("OAuth exchange failed")
        return "<h3>授權交換失敗</h3><p>請回到 LINE 重新傳送「連結 Google」再試一次。</p>", 500

    return (
        "<h2>Google 帳號已連結成功</h2>"
        "<p>可以關閉此頁，回到 LINE 跟秘書說話了。</p>"
        "<p>試試：「今天有什麼行程？」「有哪些未讀信件？」</p>"
    )


@app.get("/oauth/ms/callback")
def ms_oauth_callback():
    error = request.args.get("error")
    if error:
        desc = request.args.get("error_description", "")
        logger.warning("Microsoft 授權失敗: %s %s", error, desc[:200])
        # 常見：需要系統管理員同意（AADSTS65001 等）——提示使用者找 IT。
        return (
            "<h3>Outlook 授權失敗</h3>"
            f"<p>{error}</p>"
            "<p>若訊息提到需要管理員核准（admin consent），"
            "請聯絡公司 IT 於 Azure 授權此應用程式。</p>"
        ), 400

    code = request.args.get("code")
    state = request.args.get("state")  # LINE user id
    if not code or not state:
        return "<h3>缺少 code 或 state</h3>", 400

    try:
        ms_exchange_code(code, state)
    except Exception:  # noqa: BLE001
        logger.exception("Microsoft OAuth exchange failed")
        return "<h3>授權交換失敗</h3><p>請回到 LINE 重新傳送「連結 Outlook」再試一次。</p>", 500

    return (
        "<h2>Outlook 帳號已連結成功</h2>"
        "<p>可以關閉此頁，回到 LINE。</p>"
        "<p>試試：「Outlook 有什麼未讀信？」</p>"
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
