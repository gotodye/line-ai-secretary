#!/usr/bin/env pwsh
# Sync local .env secrets to a Render web service via Render API.
# Usage:
#   $env:RENDER_API_KEY = "rnd_..."
#   .\scripts\sync_render_env.ps1 -ServiceId srv-xxxxx
# Or auto-find service by name:
#   .\scripts\sync_render_env.ps1 -ServiceName line-ai-secretary

param(
    [string]$ServiceId = "",
    [string]$ServiceName = "line-ai-secretary",
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"
$apiKey = $env:RENDER_API_KEY
if (-not $apiKey) {
    Write-Error "請先設定 RENDER_API_KEY。Render Dashboard → Account Settings → API Keys"
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "找不到 $EnvFile"
}

$headers = @{
    Authorization = "Bearer $apiKey"
    Accept        = "application/json"
    "Content-Type" = "application/json"
}

function Invoke-RenderApi {
    param([string]$Method, [string]$Uri, [object]$Body = $null)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $headers }
    if ($Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6) }
    return Invoke-RestMethod @params
}

if (-not $ServiceId) {
    Write-Host "查找 Render service: $ServiceName ..."
    $services = Invoke-RenderApi GET "https://api.render.com/v1/services?limit=100"
    $matches_ = @($services | ForEach-Object { $_.service } | Where-Object { $_.name -eq $ServiceName })

    if ($matches_.Count -eq 0) {
        Write-Error "找不到名為 '$ServiceName' 的 service。請先在 Render 建立 Web Service，或指定 -ServiceId"
    }
    # Render 允許同名服務（例如舊的沒刪、新的又建一個），同名時網址才是唯一的區別。
    # 這裡不猜，直接要求指定 ServiceId，免得把設定推到已停用的舊服務上。
    if ($matches_.Count -gt 1) {
        Write-Host ""
        Write-Host "有 $($matches_.Count) 個服務同樣叫 '$ServiceName'："
        foreach ($m in $matches_) {
            Write-Host "  $($m.id)  $($m.serviceDetails.url)  [$($m.suspended)]"
        }
        Write-Host ""
        Write-Error "請用 -ServiceId 指定要更新哪一個（挑 suspended 為 not_suspended 的那個）"
    }
    $match = $matches_[0]
    $ServiceId = $match.id
    Write-Host "找到 service id: $ServiceId"
} else {
    $match = (Invoke-RenderApi GET "https://api.render.com/v1/services/$ServiceId")
}

if ($match.suspended -eq "suspended") {
    Write-Error "此 service 已被 Render 停用（suspended），推設定上去不會生效。請確認 ServiceId 是否選錯。"
}

# 用 Render 回報的實際網址，不要從服務名稱推導。
# 名稱衝突時 Render 會加上隨機後綴（例：line-ai-secretary-gvxw.onrender.com），
# 推導出來的網址會指向別的服務，導致 OAuth redirect_uri 全錯。
$baseUrl = $match.serviceDetails.url
if (-not $baseUrl) {
    Write-Error "無法從 Render API 取得 service 網址，請確認 ServiceId 是否為 web service"
}
$baseUrl = $baseUrl.TrimEnd('/')
Write-Host "Render 實際網址: $baseUrl"
$vars = @{
    LINE_CHANNEL_SECRET         = $null
    LINE_CHANNEL_ACCESS_TOKEN   = $null
    GEMINI_API_KEY              = $null
    GEMINI_MODEL                = "gemini-2.5-flash"
    GOOGLE_CLIENT_ID            = $null
    GOOGLE_CLIENT_SECRET        = $null
    FLASK_SECRET_KEY            = $null
    BASE_URL                    = $baseUrl
    GOOGLE_REDIRECT_URI         = "$baseUrl/oauth/callback"
    UPSTASH_REDIS_REST_URL      = $null
    UPSTASH_REDIS_REST_TOKEN    = $null
    TOKEN_ENCRYPTION_KEY        = $null
    DATA_DIR                    = "/var/data"
    PYTHON_VERSION              = "3.12.0"
}

# BASE_URL / GOOGLE_REDIRECT_URI 一律以 Render 實際網址為準，不讓 .env 覆蓋，
# 否則 .env 裡的舊網址會被同步上線，OAuth 就會導回錯誤（甚至已停用）的網域。
$derivedOnly = @("BASE_URL", "GOOGLE_REDIRECT_URI")

Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
        $k = $matches[1]
        $v = $matches[2].Trim().Trim('"')
        if (-not $vars.ContainsKey($k) -or -not $v) { return }
        if ($derivedOnly -contains $k) {
            if ($v -ne $vars[$k]) {
                Write-Warning "$EnvFile 的 $k=$v 與 Render 實際網址不符，改用 $($vars[$k])"
            }
            return
        }
        $vars[$k] = $v
    }
}

if (-not $vars.FLASK_SECRET_KEY) {
    $vars.FLASK_SECRET_KEY = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
}

# 與 app/config.py 的 require_store_config() 一致：設定不完整就別推上去，
# 否則 gunicorn 開機失敗、服務直接掛掉。
if ($vars.UPSTASH_REDIS_REST_URL -xor $vars.UPSTASH_REDIS_REST_TOKEN) {
    Write-Error "UPSTASH_REDIS_REST_URL 與 UPSTASH_REDIS_REST_TOKEN 必須同時設定"
}
if ($vars.UPSTASH_REDIS_REST_URL -and -not $vars.TOKEN_ENCRYPTION_KEY) {
    Write-Error "使用 Upstash 時必須設定 TOKEN_ENCRYPTION_KEY，請先執行 .\scripts\generate_keys.ps1"
}
if (-not $vars.UPSTASH_REDIS_REST_URL) {
    Write-Warning "未設定 Upstash，正式環境的授權與對話記憶會在每次重啟後遺失"
}

Write-Host "更新 Render 環境變數 ..."
foreach ($entry in $vars.GetEnumerator()) {
    if (-not $entry.Value) { continue }
    $body = @{ envVar = @{ key = $entry.Key; value = [string]$entry.Value } }
    try {
        Invoke-RenderApi PUT "https://api.render.com/v1/services/$ServiceId/env-vars/$($entry.Key)" $body | Out-Null
        Write-Host "  OK $($entry.Key)"
    } catch {
        # create if missing
        Invoke-RenderApi POST "https://api.render.com/v1/services/$ServiceId/env-vars" $body | Out-Null
        Write-Host "  ADD $($entry.Key)"
    }
}

Write-Host ""
Write-Host "完成。請確認："
Write-Host "  BASE_URL=$baseUrl"
Write-Host "  LINE Webhook=$baseUrl/callback"
Write-Host "  Google Redirect=$baseUrl/oauth/callback"
Write-Host ""
Write-Host "觸發重新部署："
Write-Host "  Invoke-RestMethod -Method POST -Uri https://api.render.com/v1/services/$ServiceId/deploys -Headers @{Authorization='Bearer '+`$env:RENDER_API_KEY}"
