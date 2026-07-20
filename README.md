# LINE AI 秘書

透過 LINE 傳訊息，串接 **Google AI Studio（Gemini）**，並可授權連結 **Google Calendar / Gmail / Drive / Tasks / Sheets**。

## 功能

| 類型 | 能力 |
|------|------|
| 對話秘書 | 摘要、草擬、翻譯、規劃（Gemini） |
| 日曆 | 查即將到來的行程、建立行程 |
| Gmail | 讀取信件摘要、寄信 |
| Drive | 搜尋／列出最近檔案 |
| Tasks | 列出／新增待辦 |
| Sheets | 讀取指定試算表範圍 |

在 LINE 傳 **「說明」** 可看指令；傳 **「連結 Google」** 完成授權後即可用語音式自然語言操作上述服務。

## 架構

```
LINE 使用者
  → LINE Platform (webhook)
  → 本服務 /callback
  → 立刻 reply「收到…」+ 背景處理
  → Gemini（可 function call Google APIs）
  → LINE push 回覆

Google 授權：
  LINE「連結 Google」→ 瀏覽器 OAuth → /oauth/callback → 存 refresh token（依 LINE user id）
```

## 事前準備

### 1. LINE Developers（你已有機器人）

1. 開啟 [LINE Developers Console](https://developers.line.biz/)
2. Messaging API channel 取得：
   - **Channel secret**
   - **Channel access token**（Long-lived）
3. 先暫時不填 Webhook（等有公開 HTTPS 再填）
4. 建議關閉 **Auto-reply**、**Greeting message**（避免與 AI 搶回覆）

### 2. Google AI Studio

1. 開啟 [Google AI Studio](https://aistudio.google.com/)
2. 建立 **API key** → 填入 `GEMINI_API_KEY`

### 3. Google Cloud（串接各項 Google 服務）

1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案
2. 啟用 API：
   - Google Calendar API
   - Gmail API
   - Google Drive API
   - Google Tasks API
   - Google Sheets API
3. **OAuth consent screen**
   - User type：External（個人）或 Internal（Workspace）
   - 加上自己的測試使用者 email（若還在 Testing）
   - Scopes：日曆、Gmail、Drive、Tasks、Sheets、openid、email、profile（本專案已在程式列出）
4. **Credentials → Create OAuth client ID**
   - Application type：**Web application**
   - Authorized redirect URIs（本機測試範例）：
     - `https://你的ngrok網域/oauth/callback`
   - 正式環境再加正式網域
5. 取得 **Client ID**、**Client Secret** 填入 `.env`

> 注意：OAuth 應用若在 Testing，只有測試使用者能授權；要給其他人用需送審正式發布。

## 安裝與啟動（Windows）

```bat
cd C:\Users\Angus\Projects\line-ai-secretary
copy .env.example .env
run.bat
```

或手動：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM 編輯 .env 填入金鑰
python -m app.main
```

### `.env` 必填

```env
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
GEMINI_API_KEY=...
BASE_URL=https://xxxx.ngrok-free.app
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://xxxx.ngrok-free.app/oauth/callback
FLASK_SECRET_KEY=換成一串隨機字串
```

## 本機用 ngrok 接 LINE

1. 啟動本服務（預設 `http://0.0.0.0:8000`）
2. 另開終端：`ngrok http 8000`
3. 把 HTTPS 網址寫入 `.env` 的 `BASE_URL` 與 `GOOGLE_REDIRECT_URI`
4. Google Cloud 的 Redirect URI 也要同一網址 `/oauth/callback`
5. LINE Console → Webhook URL：`https://xxxx.ngrok-free.app/callback` → Verify → 開啟 Use webhook
6. 加機器人好友，傳「說明」

## LINE 常用指令

- `說明` — 功能說明
- `連結 Google` — 開啟授權網址
- `解除 Google` — 取消授權
- `狀態` — 查看設定／連結狀態
- `清除對話` — 清除短期記憶

自然語言範例：

- 「今天有什麼行程？」
- 「明天下午 3 點到 4 點幫我約『專案檢討』」
- 「有哪些未讀信？」
- 「在 Drive 搜尋合約」
- 「待辦加上：週五前提交報表」

## 目錄結構

```
line-ai-secretary/
  app/
    main.py              # Flask：/callback、/oauth/callback
    line_bot.py          # LINE webhook
    secretary.py         # 指令與路由
    gemini_client.py     # Gemini + function calling
    google_oauth.py      # OAuth 授權
    google_services.py   # Calendar / Gmail / Drive / Tasks / Sheets
    memory.py            # 對話與 token 本地 JSON
    config.py
  data/                  # 執行後自動產生（勿提交）
  requirements.txt
  .env.example
  run.bat
```

## GitHub + Render 部署（推薦）

若你已有 GitHub 與 Render，完整步驟見 **[docs/render_deploy.md](docs/render_deploy.md)**。

### 快速版

1. Push 此 repo 到 GitHub（不要 push `.env`）
2. Render → **New Web Service** → 連 GitHub repo
3. Start Command：
   ```
   gunicorn app.main:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
   ```
4. 部署成功後取得網址，例如 `https://line-ai-secretary.onrender.com`
5. 在 Render Environment 設定：
   ```env
   BASE_URL=https://line-ai-secretary.onrender.com
   GOOGLE_REDIRECT_URI=https://line-ai-secretary.onrender.com/oauth/callback
   ```
   以及 LINE / Gemini / Google 金鑰
6. LINE Webhook：`https://line-ai-secretary.onrender.com/callback`
7. Google Redirect URI：同上 `/oauth/callback`

repo 已含 `render.yaml`，也可用 Render **Blueprint** 一鍵建立。

### 注意

- Free 方案會休眠，首次請求較慢；LINE webhook 驗證前可先開 `/health` 喚醒
- 重部署後 Google 授權可能需重新「連結 Google」（除非加 Persistent Disk）
- 金鑰只放 Render Environment，不要 commit 到 GitHub

## 安全提醒

- 不要把 Channel Secret、Access Token、Gemini Key、Google Client Secret 提交到 git
- 寄信／建行程由模型觸發：請在對話中明確確認再執行重要操作
- 本機 `data/` 含 refresh token，等同帳號存取權，請妥善保管

## 下一步可擴充

- Google Contacts / Docs / Meet
- 排程推播提醒（Cloud Scheduler + LINE Push）
- 多使用者正式 DB、管理員白名單
- 圖片／PDF 多模態理解
