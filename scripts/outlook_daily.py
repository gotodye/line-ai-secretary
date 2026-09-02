"""本機每日讀 Outlook 未讀信、整理成兩類摘要、推播到 LINE。

只能在裝有「傳統版 Outlook」且已登入的 Windows 上跑（新版 Outlook 沒有
自動化介面）。設計成由 Windows 工作排程器在使用者登入的工作階段執行。

用法：
    python scripts/outlook_daily.py            # 正式：讀 Outlook 並推 LINE
    python scripts/outlook_daily.py --dry-run  # 讀 Outlook 但只印出、不推播
    python scripts/outlook_daily.py --sample    # 用假資料測試格式與推播（不碰 Outlook）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
# 推播對象：你的 LINE user id。
OWNER_USER_ID = os.environ.get("LINE_OWNER_USER_ID", "").strip()

MAX_FETCH = 15


def read_unread() -> list[dict]:
    """透過已登入的傳統版 Outlook 讀未讀信（附加到執行中的實例，否則啟動）。"""
    import pythoncom
    import win32com.client as com

    pythoncom.CoInitialize()
    try:
        app = com.GetActiveObject("Outlook.Application")
    except Exception:
        app = com.Dispatch("Outlook.Application")

    ns = app.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)  # olFolderInbox
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    unread = items.Restrict("[Unread] = True")

    out = []
    for m in unread:
        try:
            out.append(
                {
                    "from": (getattr(m, "SenderName", "") or "").strip(),
                    "subject": (getattr(m, "Subject", "") or "(無主旨)").strip(),
                    "received": str(getattr(m, "ReceivedTime", "")),
                }
            )
        except Exception:
            continue
        if len(out) >= MAX_FETCH:
            break
    return out


_FORMAT_PROMPT = """以下是使用者 Outlook 信箱的未讀信件清單。整理成一則適合早上在 LINE 手機上快速讀完的摘要：

- 開頭一行：「📧 Outlook 未讀 N 封」
- 分兩類，每封寫「寄件者：主旨」：
  【重要】需要留意或處理的：帳單/繳費、公司或工作、真人來信、需回覆或有期限的。最多 5 封。
  【值得注意的促銷】對使用者可能有用的：划算優惠、點數/紅利即將到期、降價、職缺、活動。最多 4 封。
  這兩類有內容就逐封列出，不要縮寫成數量。
- 其餘純洗版廣告/一般電子報不逐列，末尾補一句「另有 N 封一般廣告／電子報」。
- 某類沒內容就整類略過。精簡、無客套話。

未讀清單：
{emails}
"""


def format_summary(emails: list[dict]) -> str:
    if not emails:
        return "📧 Outlook 目前沒有未讀信。"

    listing = "\n".join(
        f"- {e['from']}｜{e['subject']}（{e['received']}）" for e in emails
    )

    if not GEMINI_API_KEY:
        # 沒有金鑰就退回純列表。
        return "📧 Outlook 未讀 %d 封\n%s" % (len(emails), listing)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_FORMAT_PROMPT.format(emails=listing),
            config=types.GenerateContentConfig(temperature=0.3),
        )
        text = (getattr(resp, "text", "") or "").strip()
        return text or ("📧 Outlook 未讀 %d 封\n%s" % (len(emails), listing))
    except Exception as e:  # noqa: BLE001
        print(f"（Gemini 整理失敗，改用純列表：{e}）")
        return "📧 Outlook 未讀 %d 封\n%s" % (len(emails), listing)


def push_to_line(text: str) -> None:
    if not LINE_TOKEN:
        raise RuntimeError("缺少 LINE_CHANNEL_ACCESS_TOKEN")
    if not OWNER_USER_ID:
        raise RuntimeError("缺少 LINE_OWNER_USER_ID（要推給誰）")
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {LINE_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"to": OWNER_USER_ID, "messages": [{"type": "text", "text": text[:4900]}]},
        timeout=20,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"LINE 推播失敗 HTTP {resp.status_code}: {resp.text[:200]}")


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    sample = "--sample" in argv

    if sample:
        emails = [
            {"from": "中國信託銀行", "subject": "【本週五截止】信貸折扣金NT2,000元", "received": "2026-09-02 08:10"},
            {"from": "同事 Kevin", "subject": "Re: 週五會議簡報請補上Q3數字", "received": "2026-09-02 07:55"},
            {"from": "momo購物網", "subject": "💯中獎！限時領取", "received": "2026-09-02 06:30"},
            {"from": "LinkedIn", "subject": "台灣區營運經理職缺配對", "received": "2026-09-02 05:12"},
            {"from": "電子報週刊", "subject": "本週精選文章", "received": "2026-09-01 22:00"},
        ]
    else:
        try:
            emails = read_unread()
        except Exception as e:  # noqa: BLE001
            print(f"讀取 Outlook 失敗：{e}")
            print("請確認：已切回『傳統版 Outlook』、Outlook 正在執行、且此程式在你登入的工作階段執行。")
            return 1
        print(f"讀到 {len(emails)} 封未讀")

    text = format_summary(emails)
    print("-" * 50)
    print(text)
    print("-" * 50)

    if dry_run:
        print("(--dry-run：未推播)")
        return 0

    push_to_line(text)
    print("已推播到 LINE ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
