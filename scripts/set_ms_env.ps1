#!/usr/bin/env pwsh
# 只新增/更新 Outlook / Microsoft 相關的 Render 環境變數，其餘保持不變。
#
# 用法（在專案根目錄的終端機執行）：
#   $env:RENDER_API_KEY   = "rnd_..."      # Render Dashboard → Account Settings → API Keys
#   $env:MS_CLIENT_SECRET = "你的secret"    # Azure → Certificates & secrets 的 Value
#   pwsh scripts/set_ms_env.ps1
#
# client id / tenant id 從 .env 讀；redirect uri 自動用正式網址推導。
# 兩個機密都只留在你的終端機，不會寫進任何檔案。

param(
    [string]$ServiceUrl = "https://line-ai-secretary-gvxw.onrender.com",
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"
$apiKey = $env:RENDER_API_KEY
if (-not $apiKey) { Write-Error "請先設定 `$env:RENDER_API_KEY" }
if (-not (Test-Path $EnvFile)) { Write-Error "找不到 $EnvFile" }

$headers = @{ Authorization = "Bearer $apiKey"; Accept = "application/json"; "Content-Type" = "application/json" }

# 從 .env 讀 client id / tenant id
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $envMap[$matches[1]] = $matches[2].Trim().Trim('"') }
}

$msVars = [ordered]@{
    MS_CLIENT_ID     = $envMap["MS_CLIENT_ID"]
    MS_TENANT_ID     = $envMap["MS_TENANT_ID"]
    MS_REDIRECT_URI  = "$ServiceUrl/oauth/ms/callback"
    MS_CLIENT_SECRET = $env:MS_CLIENT_SECRET
}
if (-not $msVars.MS_CLIENT_ID -or -not $msVars.MS_TENANT_ID) {
    Write-Error "$EnvFile 缺少 MS_CLIENT_ID 或 MS_TENANT_ID"
}
if (-not $msVars.MS_CLIENT_SECRET) {
    Write-Warning "未設定 `$env:MS_CLIENT_SECRET —— 這次不會設 secret，你要自己到 Render 後台補上"
}

# 用網址精準找到正式服務（避免兩個同名服務選錯）
Write-Host "查找服務 $ServiceUrl ..."
$services = Invoke-RestMethod -Method GET -Uri "https://api.render.com/v1/services?limit=100" -Headers $headers
$svc = $services | ForEach-Object { $_.service } | Where-Object { $_.serviceDetails.url -eq $ServiceUrl } | Select-Object -First 1
if (-not $svc) { Write-Error "找不到網址為 $ServiceUrl 的服務" }
$sid = $svc.id
Write-Host "找到 service id: $sid"

# 讀出目前所有環境變數（Render 只支援「整批取代」，所以先合併再寫回，
# 否則單設一個會把其他變數全刪掉）
Write-Host "讀取現有環境變數 ..."
$current = @{}
$cursor = $null
while ($true) {
    $uri = "https://api.render.com/v1/services/$sid/env-vars?limit=100"
    if ($cursor) { $uri += "&cursor=$cursor" }
    $page = Invoke-RestMethod -Method GET -Uri $uri -Headers $headers
    if (-not $page -or $page.Count -eq 0) { break }
    foreach ($row in $page) {
        if ($row.envVar) { $current[$row.envVar.key] = $row.envVar.value }
        $cursor = $row.cursor
    }
    if ($page.Count -lt 100) { break }
}
Write-Host "  目前有 $($current.Count) 個環境變數"

# 合併 MS 變數（覆蓋同名、其餘保留）
foreach ($entry in $msVars.GetEnumerator()) {
    if ($entry.Value) {
        $action = if ($current.ContainsKey($entry.Key)) { "更新" } else { "新增" }
        $current[$entry.Key] = [string]$entry.Value
        Write-Host "  $action $($entry.Key)"
    }
}

# 整批寫回（陣列格式，-AsArray 確保單元素也是 JSON 陣列）
$payload = @($current.GetEnumerator() | ForEach-Object { @{ key = $_.Key; value = $_.Value } })
$json = $payload | ConvertTo-Json -Depth 6 -AsArray
Write-Host "寫回 $($payload.Count) 個環境變數 ..."
Invoke-RestMethod -Method PUT -Uri "https://api.render.com/v1/services/$sid/env-vars" -Headers $headers -Body $json | Out-Null

Write-Host "觸發重新部署 ..."
Invoke-RestMethod -Method POST -Uri "https://api.render.com/v1/services/$sid/deploys" -Headers $headers -Body "{}" | Out-Null
Write-Host ""
Write-Host "完成。等部署轉 Live 後，在 LINE 傳「連結 Outlook」。"
