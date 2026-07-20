#!/usr/bin/env pwsh
# One-shot setup: create Render service (if needed), sync env vars, trigger deploy.
# Prerequisite: set RENDER_API_KEY once in this PowerShell session.

param(
    [string]$ServiceName = "line-ai-secretary"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $env:RENDER_API_KEY) {
    Write-Error @"
請先設定 Render API Key（只需一次）：

1. 開啟 https://dashboard.render.com/u/settings#api-keys
2. Create API Key
3. 在本終端執行：
   `$env:RENDER_API_KEY = "rnd_你的key"

4. 再執行：
   .\scripts\setup_all.ps1
"@
}

# Ensure local .env has Render URLs + secret
$envPath = ".env"
$baseUrl = "https://$ServiceName.onrender.com"
$secret = & python -c "import secrets; print(secrets.token_urlsafe(32))"

if (Test-Path $envPath) {
    $content = Get-Content $envPath -Raw
    $content = $content -replace '(?m)^BASE_URL=.*$', "BASE_URL=$baseUrl"
    $content = $content -replace '(?m)^GOOGLE_REDIRECT_URI=.*$', "GOOGLE_REDIRECT_URI=$baseUrl/oauth/callback"
    if ($content -notmatch '(?m)^FLASK_SECRET_KEY=.{20,}') {
        $content = $content -replace '(?m)^FLASK_SECRET_KEY=.*$', "FLASK_SECRET_KEY=$secret"
    }
    Set-Content -Path $envPath -Value $content.TrimEnd() -Encoding utf8
    Write-Host "已更新本地 .env 的 BASE_URL / GOOGLE_REDIRECT_URI"
}

$headers = @{
    Authorization = "Bearer $($env:RENDER_API_KEY)"
    Accept        = "application/json"
    "Content-Type" = "application/json"
}

$services = Invoke-RestMethod -Method GET -Uri "https://api.render.com/v1/services?limit=100" -Headers $headers
$service = $services | ForEach-Object { $_.service } | Where-Object { $_.name -eq $ServiceName } | Select-Object -First 1

if (-not $service) {
    Write-Host "Render 上尚無 $ServiceName，正在建立 ..."
    & "$PSScriptRoot\create_render_service.ps1" -ServiceName $ServiceName
    Start-Sleep -Seconds 3
    $services = Invoke-RestMethod -Method GET -Uri "https://api.render.com/v1/services?limit=100" -Headers $headers
    $service = $services | ForEach-Object { $_.service } | Where-Object { $_.name -eq $ServiceName } | Select-Object -First 1
}

if (-not $service) {
    Write-Error "建立 service 失敗，請到 Render Dashboard 手動連 GitHub repo。"
}

Write-Host "Service ID: $($service.id)"
& "$PSScriptRoot\sync_render_env.ps1" -ServiceId $service.id -ServiceName $ServiceName

Write-Host "觸發部署 ..."
Invoke-RestMethod -Method POST -Uri "https://api.render.com/v1/services/$($service.id)/deploys" -Headers $headers | Out-Null

Write-Host ""
Write-Host "=========================================="
Write-Host "Render 設定完成。請手動完成以下兩項（我無法代登入）："
Write-Host ""
Write-Host "LINE Developers → Webhook URL:"
Write-Host "  $baseUrl/callback"
Write-Host ""
Write-Host "Google Cloud → OAuth Redirect URI:"
Write-Host "  $baseUrl/oauth/callback"
Write-Host ""
Write-Host "等 2-3 分鐘部署完成後測試："
Write-Host "  $baseUrl/health"
Write-Host "=========================================="
