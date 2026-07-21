#!/usr/bin/env pwsh
# 產生 TOKEN_ENCRYPTION_KEY（Fernet 金鑰），貼進 .env 後再用 sync_render_env.ps1 同步上 Render。
#
# 注意：金鑰更換後，先前加密的 Google token 一律無法解密，
# 所有使用者都必須重新傳送「連結 Google」授權一次。

$ErrorActionPreference = "Stop"

$key = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
if ($LASTEXITCODE -ne 0) {
    Write-Error "產生失敗。請先安裝相依套件：pip install -r requirements.txt"
}

Write-Host ""
Write-Host "把這行加進 .env（若已存在請直接取代）："
Write-Host ""
Write-Host "TOKEN_ENCRYPTION_KEY=$key"
Write-Host ""
Write-Host "接著同步到 Render："
Write-Host "  .\scripts\sync_render_env.ps1 -ServiceName line-ai-secretary-gvxw"
