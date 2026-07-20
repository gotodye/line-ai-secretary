"""High-level secretary commands and message routing."""

from __future__ import annotations

from app import config
from app import gemini_client
from app import memory
from app.google_oauth import GoogleNotConfiguredError, build_auth_url

HELP_TEXT = """我是你的 AI 秘書，可以：

【一般】
・摘要、草擬、翻譯、規劃待辦
・自然語言對話

【Google 服務】（需先連結）
・日曆：查行程、建立行程
・Gmail：讀信、寄信
・Drive：搜尋／列出檔案
・Tasks：列出／新增待辦
・Sheets：讀取試算表範圍

【指令】
・說明 / 幫助 — 顯示此說明
・連結 Google — 授權 Google 帳號
・解除 Google — 取消授權
・清除對話 — 忘掉近期對話
・狀態 — 查看連結狀態

直接用中文說需求即可，例如：
「今天有什麼行程？」
「幫我寄信給 xxx@example.com，主旨……」
「在待辦加上：準備簡報」
"""


def handle_text(user_id: str, text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "請傳送文字訊息。"

    cmd = raw.replace(" ", "")

    if cmd in ("說明", "幫助", "help", "/help", "？", "?"):
        return HELP_TEXT

    if cmd in ("狀態", "status"):
        linked = memory.is_google_linked(user_id)
        oauth_ok = config.google_oauth_configured()
        return (
            f"Gemini 模型：{config.GEMINI_MODEL}\n"
            f"Google OAuth 設定：{'已設定' if oauth_ok else '未設定'}\n"
            f"你的 Google 帳號：{'已連結' if linked else '未連結'}\n"
            f"公開網址 BASE_URL：{config.BASE_URL or '（未設定）'}"
        )

    if cmd in ("清除對話", "清除紀錄", "reset"):
        memory.clear_history(user_id)
        return "已清除近期對話記憶。"

    if cmd in ("解除Google", "解除連結", "unlink", "取消授權"):
        memory.delete_google_token(user_id)
        return "已解除 Google 帳號連結。"

    if cmd in ("連結Google", "連結google", "連接Google", "授權Google", "link"):
        if not config.google_oauth_configured():
            return (
                "伺服器尚未設定 Google OAuth。\n"
                "請在 .env 填入 GOOGLE_CLIENT_ID、GOOGLE_CLIENT_SECRET，"
                "並設定 BASE_URL / GOOGLE_REDIRECT_URI。"
            )
        try:
            url = build_auth_url(user_id)
        except GoogleNotConfiguredError as e:
            return str(e)
        return (
            "請用手機瀏覽器開啟以下連結，登入並允許存取：\n\n"
            f"{url}\n\n"
            "授權完成後回到 LINE，就可以查日曆、郵件、Drive、待辦了。"
        )

    # Default: Gemini with tools
    history = memory.get_history(user_id)
    answer = gemini_client.chat(user_id, raw, history)
    memory.append_history(user_id, "user", raw)
    memory.append_history(user_id, "assistant", answer)
    return answer[:4900]
