"""High-level secretary commands and message routing."""

from __future__ import annotations

from app import config
from app import gemini_client
from app import memory
from app.google_oauth import GoogleNotConfiguredError, build_auth_url

# 帶進模型的對話輪數；儲存端保留較多，這裡只取最近的。
HISTORY_TURNS = 12

HELP_TEXT = """我是你的 AI 秘書，可以：

【一般】
・摘要、草擬、翻譯、規劃待辦
・查天氣、新聞、股價等即時資訊
・看圖片、聽語音訊息

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
・Outlook 信件 / 讀 Outlook — 請你電腦讀 Outlook 最新未讀信
・清除對話 — 忘掉近期對話
・記憶 — 列出我記住的事
・忘記 XXX — 忘掉某件事
・狀態 — 查看連結狀態

直接用中文說需求即可，例如：
「今天有什麼行程？」
「幫我寄信給 xxx@example.com，主旨……」
「在待辦加上：準備簡報」
「台北明天會下雨嗎？」

我會自己記住值得長期記住的事，例如你的稱謂、偏好、
常聯絡的人，之後就不用重複交代。
"""


def handle_text(
    user_id: str, text: str, attachment: tuple[bytes, str] | None = None
) -> str:
    raw = (text or "").strip()
    if not raw:
        return "請傳送文字訊息。"

    # 有附件時一律交給模型處理，不要被指令比對攔截。
    if attachment:
        full = memory.get_full_history(user_id)
        answer = gemini_client.chat(
            user_id, raw, full[-HISTORY_TURNS:], attachment=attachment
        )
        memory.append_exchange(user_id, raw, answer, known_full=full)
        return answer

    cmd = raw.replace(" ", "")

    # Outlook 讀信：雲端碰不到公司信箱，改記旗標讓使用者電腦上的看守程式去讀。
    low = cmd.lower()
    if "outlook" in low and (
        cmd in ("outlook", "Outlook")
        or any(k in cmd for k in ("信", "讀", "郵件", "未讀", "收"))
        or "mail" in low
    ):
        memory.request_outlook_read(user_id)
        return (
            "好，我請你電腦上的 Outlook 讀取器去讀最新未讀信，稍等一下下就傳給你。\n"
            "（需要你的電腦開著、傳統版 Outlook 開著；沒開的話會等下次開機／排程時間）"
        )

    if cmd in ("說明", "幫助", "help", "/help", "？", "?"):
        return HELP_TEXT

    if cmd in ("狀態", "status"):
        return (
            f"Gemini 模型：{config.GEMINI_MODEL}\n"
            f"Google OAuth 設定：{'已設定' if config.google_oauth_configured() else '未設定'}\n"
            f"你的 Google 帳號：{'已連結' if memory.is_google_linked(user_id) else '未連結'}\n"
            f"Outlook：由本機讀取器處理（傳「Outlook 信件」或每天早上自動讀）\n"
            f"公開網址 BASE_URL：{config.BASE_URL or '（未設定）'}"
        )

    if cmd in ("清除對話", "清除紀錄", "reset"):
        memory.clear_history(user_id)
        return "已清除近期對話記憶。"

    if cmd in ("記憶", "記得什麼", "memory"):
        facts = memory.get_facts(user_id)
        if not facts:
            return "我還沒記住關於你的事。聊久一點我會自己記下值得記的。"
        listed = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1))
        return f"我記得這些事：\n\n{listed}\n\n要我忘記某一項，說「忘記 <關鍵字>」。"

    if cmd in ("清除記憶", "忘記全部", "忘記所有"):
        memory.clear_facts(user_id)
        return "已忘記所有長期記憶。"

    if cmd.startswith("忘記") and len(cmd) > 2:
        return memory.remove_fact(user_id, cmd[2:])

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

    if cmd in ("連結Outlook", "連結outlook", "連接Outlook", "授權Outlook", "解除Outlook", "解除outlook"):
        # 雲端直連 Outlook 需公司 IT 管理員核准（目前被擋），改由本機讀取器處理。
        return (
            "Outlook 目前改由你電腦上的讀取器處理，不需要在這裡連結。\n"
            "直接傳「Outlook 信件」或「讀 Outlook」，我就會請你的電腦讀最新未讀信給你。\n"
            "每天早上也會自動讀一次。"
        )

    # Default: Gemini with tools
    # 讀一次、寫一次：把完整歷史留著回傳給 append_exchange，避免重複讀取。
    full = memory.get_full_history(user_id)
    answer = gemini_client.chat(user_id, raw, full[-HISTORY_TURNS:])
    memory.append_exchange(user_id, raw, answer, known_full=full)
    return answer[:4900]
