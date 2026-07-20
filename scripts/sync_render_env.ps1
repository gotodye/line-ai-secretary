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
    $match = $services | ForEach-Object { $_.service } | Where-Object { $_.name -eq $ServiceName } | Select-Object -First 1
    if (-not $match) {
        Write-Error "找不到名為 '$ServiceName' 的 service。請先在 Render 建立 Web Service，或指定 -ServiceId"
    }
    $ServiceId = $match.id
    Write-Host "找到 service id: $ServiceId"
}

$baseUrl = "https://$ServiceName.onrender.com"
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
    DATA_DIR                    = "/var/data"
    PYTHON_VERSION              = "3.12.0"
}

Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
        $k = $matches[1]
        $v = $matches[2].Trim().Trim('"')
        if ($vars.ContainsKey($k) -and $v) { $vars[$k] = $v }
    }
}

if (-not $vars.FLASK_SECRET_KEY) {
    $vars.FLASK_SECRET_KEY = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
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
