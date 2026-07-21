# GitHub + Render 部署指南

## 流程概覽

```
本機程式 → push GitHub → Render 自動部署 → 取得 https://xxx.onrender.com
                                              ↓
                              填入 BASE_URL / LINE Webhook / Google Redirect
```

## 1. Push 到 GitHub

在專案目錄：

```bat
git add .
git commit -m "Add LINE AI secretary with Render deploy config"
git branch -M main
git remote add origin https://github.com/你的帳號/line-ai-secretary.git
git push -u origin main
```

> 不要 commit `.env`（已在 `.gitignore`）。

## 2. 在 Render 建立 Web Service

1. 登入 [Render Dashboard](https://dashboard.render.com/)
2. **New +** → **Web Service**
3. **Connect** 你的 GitHub repo `line-ai-secretary`
4. 設定：

| 欄位 | 值 |
|------|-----|
| Name | `line-ai-secretary`（自訂） |
| Region | Singapore 或離你最近的 |
| Branch | `main` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app.main:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |
| Plan | Free（測試用） |

5. **Environment** 新增變數（見下方清單）
6. **Create Web Service**，等 Deploy 成功

也可用 **New + → Blueprint**，直接讀 repo 裡的 `render.yaml`（會提示你補 secret 變數）。

## 3. 查 BASE_URL

部署成功後，Render 會顯示公開網址，例如：

```
https://line-ai-secretary.onrender.com
```

這就是 **BASE_URL**。

在 Render → 你的 Service → **Environment** 補上：

```env
BASE_URL=https://line-ai-secretary.onrender.com
GOOGLE_REDIRECT_URI=https://line-ai-secretary.onrender.com/oauth/callback
```

儲存後 Render 會自動重新部署。

## 4. 設定 LINE Webhook

LINE Developers → Messaging API：

- **Webhook URL**：`https://line-ai-secretary.onrender.com/callback`
- 開啟 **Use webhook**
- 按 **Verify**（要 Deploy 已成功）
- 關閉 **Auto-reply messages**

## 5. 設定 Google OAuth Redirect

Google Cloud Console → Credentials → OAuth 2.0 Client → **Authorized redirect URIs**：

```
https://line-ai-secretary.onrender.com/oauth/callback
```

## 6. 測試

1. 瀏覽器開 `https://line-ai-secretary.onrender.com/health` → 應看到 `{"ok": true}`
2. LINE 加好友，傳「說明」
3. 傳「連結 Google」完成授權
4. 試「今天有什麼行程？」

## Render 環境變數清單

| 變數 | 必填 | 說明 |
|------|------|------|
| `LINE_CHANNEL_SECRET` | ✅ | LINE channel secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | LINE long-lived token |
| `GEMINI_API_KEY` | ✅ | AI Studio API key |
| `BASE_URL` | ✅ | `https://你的服務.onrender.com` |
| `GOOGLE_REDIRECT_URI` | ✅ | `{BASE_URL}/oauth/callback` |
| `GOOGLE_CLIENT_ID` | 建議 | Google OAuth |
| `GOOGLE_CLIENT_SECRET` | 建議 | Google OAuth |
| `FLASK_SECRET_KEY` | 建議 | 隨機長字串（Render 可自動產生） |
| `UPSTASH_REDIS_REST_URL` | ✅ | Upstash Console → Redis → REST API |
| `UPSTASH_REDIS_REST_TOKEN` | ✅ | 同上 |
| `TOKEN_ENCRYPTION_KEY` | ✅ | `pwsh scripts/generate_keys.ps1` 產生 |
| `GEMINI_MODEL` | 選填 | 預設 `gemini-2.5-flash` |
| `DATA_DIR` | 選填 | 僅未設 Upstash 時的本機退路 |

## 注意事項

### Free 方案冷啟動

免費版約 15 分鐘沒流量會休眠，第一次請求可能要等 30–60 秒。LINE Verify webhook 若失敗，多按幾次或先開瀏覽器造訪 `/health` 喚醒。

長期使用建議升級 **Starter**（常駐、較穩）。

### Google Token 會不會消失？

不會 —— 前提是有設定 Upstash。

Render Free 方案的檔案系統是暫存的，每次重部署或休眠重啟都會清空，所以 OAuth token 與對話記憶改存 **Upstash Redis**（免費方案永久有效，每日 10,000 次命令）。設定方式：

1. [upstash.com](https://upstash.com) 註冊 → 建立 Redis 資料庫（區域選離 Render 服務近的）
2. 資料庫頁面 → **REST API** 頁籤 → 複製 `UPSTASH_REDIS_REST_URL` 與 `UPSTASH_REDIS_REST_TOKEN`
3. `pwsh scripts/generate_keys.ps1` 產生 `TOKEN_ENCRYPTION_KEY`
4. 三個值填進 `.env`，執行 `.\scripts\sync_render_env.ps1 -ServiceName <你的服務名>`

Token 以 Fernet 加密後才寫入 Upstash，儲存端看不到明文。**更換 `TOKEN_ENCRYPTION_KEY` 會讓既有 token 全部失效**，所有使用者需重新連結。

三個變數缺一不可：設定不完整時 gunicorn 會直接開機失敗並在日誌說明原因，而不是默默以明文或暫存模式運行。未設 Upstash 時服務仍可啟動（退回本機檔案），但日誌會持續警告。

### 自動部署

Render 預設 **每次 push 到 main** 會自動重新部署，無需手動更新。
