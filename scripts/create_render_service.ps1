#!/usr/bin/env pwsh
# Create Render web service from GitHub repo (one-time).
# Requires: RENDER_API_KEY, GitHub repo already on gotodye/line-ai-secretary

param(
    [string]$ServiceName = "line-ai-secretary",
    [string]$Repo = "https://github.com/gotodye/line-ai-secretary",
    [string]$Branch = "main",
    [string]$Region = "singapore"
)

$ErrorActionPreference = "Stop"
$apiKey = $env:RENDER_API_KEY
if (-not $apiKey) {
    Write-Error @"
缺少 RENDER_API_KEY。

請到 Render Dashboard → Account Settings → API Keys 建立一把 key，然後：

  `$env:RENDER_API_KEY = "rnd_..."
  .\scripts\create_render_service.ps1
"@
}

$headers = @{
    Authorization = "Bearer $apiKey"
    Accept        = "application/json"
    "Content-Type" = "application/json"
}

$ownerId = (Invoke-RestMethod -Method GET -Uri "https://api.render.com/v1/owners?limit=20" -Headers $headers)[0].owner.id

$body = @{
    type              = "web_service"
    name              = $ServiceName
    ownerId           = $ownerId
    repo              = $Repo
    branch            = $Branch
    region            = $Region
    plan              = "free"
    autoDeploy        = "yes"
    serviceDetails    = @{
        runtime         = "python"
        buildCommand    = "pip install -r requirements.txt"
        startCommand    = "gunicorn app.main:app --bind 0.0.0.0:`$PORT --workers 1 --timeout 120"
        healthCheckPath = "/health"
        envSpecificDetails = @{
            pythonVersion = "3.12.0"
        }
    }
} | ConvertTo-Json -Depth 8

Write-Host "建立 Render Web Service: $ServiceName ..."
$result = Invoke-RestMethod -Method POST -Uri "https://api.render.com/v1/services" -Headers $headers -Body $body
$serviceId = $result.service.id
Write-Host "Service ID: $serviceId"
Write-Host "URL: https://$ServiceName.onrender.com"
Write-Host ""
Write-Host "下一步："
Write-Host "  .\scripts\sync_render_env.ps1 -ServiceId $serviceId"
