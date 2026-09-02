"""本機每日／隨時讀 Outlook 新信，依規則判讀成兩類，推播到 LINE。

增量讀取：記住上次讀到的時間點（浮水印），每次只處理「之後」收到的新信。
不論是每天 07:00 的排程、還是你臨時手動執行，都從上次讀過的地方接著讀。

只能在裝有「傳統版 Outlook」且已登入、Outlook 開著的 Windows 上跑
（新版 Outlook 沒有自動化介面）。

用法：
    python scripts/outlook_daily.py            # 讀新信並推 LINE，更新浮水印
    python scripts/outlook_daily.py --dry-run  # 讀新信只印出、不推播、不更新浮水印
    python scripts/outlook_daily.py --full      # 忽略浮水印，讀過去 24 小時（重讀用）
    python scripts/outlook_daily.py --reset      # 只清掉浮水印（下次從過去 24h 起算）
    python scripts/outlook_daily.py --sample     # 用假資料測試格式與推播（不碰 Outlook）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
OWNER_USER_ID = os.environ.get("LINE_OWNER_USER_ID", "").strip()

STATE_FILE = ROOT / "data" / "outlook_state.json"
MAX_PROCESS = 40          # 一次最多處理幾封新信（電腦關很久、累積太多時的上限）
DEFAULT_LOOKBACK_H = 24   # 沒有浮水印時往回讀幾小時

TRIAGE_RULES = """使用者本人是 Angus（中文名 禹欣 / Yu-Hsin），信箱 angus@eui.money。
以下是他新收到的 Outlook 信件（含 To/CC 與內文）。依內文判斷，嚴格遵守規則：

A. 一定看內文，不能只看主旨。
B. 判斷這封在「要求誰動作」：只有明確要求 Angus/禹欣 本人（內文稱呼他，或他是主要
   收件者 To 且被點名要動作）時，才算需要他回。若內文是在問別人（例如 Jeff、其他同事），
   即使 Angus 被 CC 也不算需要他回。
C. 下列一律不列入任何類別（使用者不需要）：交易明細、扣款、匯款/FX 確認、入帳、收據、
   credit advice 等金流通知（即使內文要求回覆確認扣款也略過）；Teams 通知；Jira 每週更新；
   廣告/電子報；「已核准/已完成」等系統結果通知。
D. Microsoft Planner「逾期/到期工作」的通知要列入第 1 類（提醒他處理）。

只輸出兩類（用這個格式）：
【需要我回覆／簽核】
- 寄件者：主旨 —— 引用內文關鍵句，並點明是對 Angus 說（重複同類申請合併，註明幾封）
【重要，留意但不必回】
- 寄件者：主旨 —— 一句話說明（報表、對帳彙總、期限、法遵/安全提醒等，內文沒要求他回）

某類沒有內容就整類略過。最後一行：其餘 N 封為金流/廣告/系統通知，已略過。
繁體中文、精簡。第 1 類寧可少列也不要誤判。
"""


def _load_watermark() -> datetime | None:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_read"])
    except Exception:
        return None


def _save_watermark(dt: datetime) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_read": dt.isoformat()}, ensure_ascii=False), encoding="utf-8"
    )


def read_new(cutoff: datetime) -> tuple[list[dict], datetime | None]:
    """讀 ReceivedTime 嚴格大於 cutoff 的新信；回傳 (清單, 最新一封的時間)。"""
    import pythoncom
    import win32com.client as com

    pythoncom.CoInitialize()
    try:
        app = com.GetActiveObject("Outlook.Application")
    except Exception:
        app = com.Dispatch("Outlook.Application")

    ns = app.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)  # 新到舊

    out: list[dict] = []
    newest: datetime | None = None
    for m in items:
        try:
            rt = m.ReceivedTime
            rt = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute, rt.second)
        except Exception:
            continue
        if newest is None:
            newest = rt
        if rt <= cutoff:
            break
        try:
            out.append(
                {
                    "from": (getattr(m, "SenderName", "") or "").strip(),
                    "email": (getattr(m, "SenderEmailAddress", "") or "").strip(),
                    "to": (getattr(m, "To", "") or "").strip(),
                    "cc": (getattr(m, "CC", "") or "").strip(),
                    "subject": (getattr(m, "Subject", "") or "(無主旨)").strip(),
                    "received": rt.strftime("%m/%d %H:%M"),
                    "body": (getattr(m, "Body", "") or "")[:2000].strip(),
                }
            )
        except Exception:
            continue
        if len(out) >= MAX_PROCESS:
            break
    return out, newest


def triage(emails: list[dict]) -> str:
    blocks = "\n\n".join(
        f"[信 {i+1}] 寄件者:{e['from']} <{e['email']}>\nTo:{e['to']}\nCC:{e['cc']}\n"
        f"主旨:{e['subject']}\n內文:\n{e['body']}"
        for i, e in enumerate(emails)
    )
    if not GEMINI_API_KEY:
        return "📧 Outlook 新信 %d 封\n%s" % (
            len(emails),
            "\n".join(f"- {e['from']}｜{e['subject']}" for e in emails),
        )
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=TRIAGE_RULES + "\n\n" + blocks,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return (getattr(resp, "text", "") or "").strip()


def push_to_line(text: str) -> None:
    if not LINE_TOKEN:
        raise RuntimeError("缺少 LINE_CHANNEL_ACCESS_TOKEN")
    if not OWNER_USER_ID:
        raise RuntimeError("缺少 LINE_OWNER_USER_ID")
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        json={"to": OWNER_USER_ID, "messages": [{"type": "text", "text": text[:4900]}]},
        timeout=20,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"LINE 推播失敗 HTTP {resp.status_code}: {resp.text[:200]}")


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    full = "--full" in argv

    if "--reset" in argv:
        STATE_FILE.unlink(missing_ok=True)
        print("已清除浮水印。")
        return 0

    if "--sample" in argv:
        text = triage([
            {"from": "Domingo (Metrobank)", "email": "x@metrobank.com.ph", "to": "Angus", "cc": "",
             "subject": "Re: KYC Documents_EUI Hong Kong",
             "body": "Hi Angus, Huang Yu Hsin is required to resubmit these forms. May I seek updates please."},
            {"from": "Kasikorn", "email": "x@kbank.com", "to": "Angus", "cc": "",
             "subject": "Credit Advice IR2609 EASTERN UNION",
             "body": "This is to advise the credit of USD... (入帳通知)"},
        ])
        print("-" * 50); print(text); print("-" * 50)
        if not dry_run:
            push_to_line(text); print("已推播 ✓")
        return 0

    watermark = None if full else _load_watermark()
    cutoff = watermark or (datetime.now() - timedelta(hours=DEFAULT_LOOKBACK_H))
    print(f"讀取 {cutoff:%Y-%m-%d %H:%M} 之後的新信...")

    try:
        emails, newest = read_new(cutoff)
    except Exception as e:  # noqa: BLE001
        print(f"讀取 Outlook 失敗：{e}")
        print("請確認：已切回傳統版 Outlook、Outlook 正在執行、且此程式在你登入的工作階段執行。")
        return 1

    print(f"新信 {len(emails)} 封")

    if not emails:
        text = f"📭 Outlook：自 {cutoff:%m/%d %H:%M} 後沒有新信。"
    else:
        header = f"📧 Outlook 新信 {len(emails)} 封（{cutoff:%m/%d %H:%M} 起）\n\n"
        text = header + triage(emails)

    print("-" * 50); print(text); print("-" * 50)

    if dry_run:
        print("(--dry-run：未推播、未更新浮水印)")
        return 0

    push_to_line(text)
    print("已推播到 LINE ✓")
    # 只有成功推播後才推進浮水印，避免漏信
    if emails and newest:
        _save_watermark(newest)
        print(f"浮水印更新到 {newest:%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
