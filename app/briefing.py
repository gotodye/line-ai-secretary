"""Proactive morning brief pushed to LINE without the user asking."""

from __future__ import annotations

import logging

from app import gemini_client
from app import memory

logger = logging.getLogger(__name__)

_BRIEF_REQUEST = """請幫我準備今天的晨間簡報。

依序做這幾件事：
1. 呼叫 list_upcoming_events 查行程（它回傳的是「從現在起」接下來的行程，
   不只今天，請自己依日期判斷哪些是今天、哪些是往後的）
2. 呼叫 list_tasks 查未完成待辦
3. 呼叫 list_recent_emails 查未讀信件（query 用 is:unread newer_than:1d）
4. 呼叫 web_search 查我所在地今天的天氣

然後整理成一則適合早上在手機上快速讀完的訊息：
- 開頭用一句話點出今天的重點（最重要的行程或截止的待辦）
- 「行程」段落一定要出現，讓我一眼就知道今天要幹嘛：
  * 今天有行程 → 條列今天的（含時間）
  * 今天沒有行程 → 明講「今天沒有安排行程」，並接著預告最近的 1-3 個未來行程
    （寫出日期與時間，例如「7/31 09:30 …」），這樣我不會漏掉隔天一早的事
  * 忽略那種掛在 1/1、明顯是年度標記或全年生效的假行程，別當成今天的事
- 信件、待辦這兩段若沒有內容就直接省略，不要寫「今天沒有待辦」這種佔版面的句子
- 天氣只講關鍵：會不會下雨、溫度範圍、要不要帶傘
- 全部控制在 15 行以內，不要有客套話
"""


def build_brief(user_id: str) -> str:
    """Generate one user's brief. Reuses the normal tool loop."""
    # 不帶對話歷史：簡報是獨立的一次性任務，混入昨天的閒聊只會干擾。
    return gemini_client.chat(user_id, _BRIEF_REQUEST, history=[])


def send_briefs(push_fn) -> dict:
    """Build and push a brief to every linked user.

    push_fn(user_id, text) 由呼叫端注入，方便測試時替換掉真正的 LINE 推播。
    """
    users = memory.list_linked_users()
    logger.info("晨間簡報：%d 位已連結使用者", len(users))

    sent, failed = [], []
    for user_id in users:
        try:
            text = build_brief(user_id)
            push_fn(user_id, text)
            sent.append(user_id)
        except Exception:  # noqa: BLE001 — 一個人失敗不該影響其他人
            logger.exception("晨間簡報失敗: %s", user_id)
            failed.append(user_id)

    return {"total": len(users), "sent": len(sent), "failed": len(failed)}
