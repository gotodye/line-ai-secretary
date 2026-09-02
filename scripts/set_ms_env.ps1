#!/usr/bin/env pwsh
# 只設定 Outlook / Microsoft 相關的 Render 環境變數，其餘不動。
#
# 用法（在專案根目錄的終端機執行）：
#   $env:RENDER_API_KEY   = "rnd_..."      # Render Dashboard → Account Settings → API Keys
#   $env:MS_CLIENT_SECRET = "你的secret"    # Azure → Certificates & secrets 的 Value
#   pwsh scripts/set_ms_env.ps1
#
# client id / tenant id 從 .env 讀；redirect uri 自動用正式網址推導。
# 兩個環境變數都只留在你的終端機，不會寫進任何檔案。

param(
    [string]$ServiceUrl = "https://line-ai-secretary-gvxw.onrender.com",
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"
$apiKey = $env:RENDER_API_KEY
if (-not $apiKey) { Write-Error "請先設定 `$env:RENDER_API_KEY" }
if (-not (Test-Path $EnvFile)) { Write-Error "找不到 $EnvFile" }

$headers = @{ Authorization = "Bearer $apiKey"; Accept = "application/json"; "Content-Type" = "application/json" }
function Invoke-RenderApi([string]$Method, [string]$Uri, [object]$Body = $null) {
    $params = @{ Method = $Method; Uri = $Uri; Headers = $headers }
    if ($Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6) }
    return Invoke-RestMethod @params
}

# 從 .env 讀 client id / tenant id
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $envMap[$matches[1]] = $matches[2].Trim().Trim('"') }
}

$vars = [ordered]@{
    MS_CLIENT_ID    = $envMap["MS_CLIENT_ID"]
    MS_TENANT_ID    = $envMap["MS_TENANT_ID"]
    MS_REDIRECT_URI = "$ServiceUrl/oauth/ms/callback"
    MS_CLIENT_SECRET = $env:MS_CLIENT_SECRET   # 只從終端機環境變數拿，不從檔案
}

if (-not $vars.MS_CLIENT_ID -or -not $vars.MS_TENANT_ID) {
    Write-Error "$EnvFile 缺少 MS_CLIENT_ID 或 MS_TENANT_ID"
}
if (-not $vars.MS_CLIENT_SECRET) {
    Write-Warning "未設定 `$env:MS_CLIENT_SECRET —— 這次不會設 secret，你要自己到 Render 後台補上"
}

# 用網址精準找到正式服務（避免兩個同名服務選錯）
Write-Host "查找服務 $ServiceUrl ..."
$services = Invoke-RenderApi GET "https://api.render.com/v1/services?limit=100"
$svc = $services | ForEach-Object { $_.service } | Where-Object { $_.serviceDetails.url -eq $ServiceUrl } | Select-Object -First 1
if (-not $svc) { Write-Error "找不到網址為 $ServiceUrl 的服務" }
$sid = $svc.id
Write-Host "找到 service id: $sid"

foreach ($entry in $vars.GetEnumerator()) {
    if (-not $entry.Value) { continue }
    $body = @{ envVar = @{ key = $entry.Key; value = [string]$entry.Value } }
    try {
        Invoke-RenderApi PUT "https://api.render.com/v1/services/$sid/env-vars/$($entry.Key)" $body | Out-Null
        Write-Host "  OK  $($entry.Key)"
    } catch {
        Invoke-RenderApi POST "https://api.render.com/v1/services/$sid/env-vars" $body | Out-Null
        Write-Host "  ADD $($entry.Key)"
    }
}

Write-Host "觸發重新部署 ..."
Invoke-RenderApi POST "https://api.render.com/v1/services/$sid/deploys" @{} | Out-Null
Write-Host "完成。等部署轉 Live 後，在 LINE 傳「連結 Outlook」。"
