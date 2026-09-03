#!/usr/bin/env pwsh
# 設定 Outlook 看守：一個隱形的常駐背景程式，登入後自動啟動、沒有任何視窗，
# 每隔幾秒默默檢查雲端旗標；你在 LINE 傳「Outlook 信件」時十幾秒內就讀。
# 取代舊的「每分鐘排程」（那會閃黑視窗）。
#
# 用法：pwsh scripts/register_outlook_watcher.ps1

param([string]$TaskName = "LINE Outlook Watcher")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$script = Join-Path $repo "scripts\outlook_daily.py"
if (-not (Test-Path $pyw)) { Write-Error "找不到 $pyw" }

# 1. 移除舊的每分鐘排程（會閃黑視窗的那個）
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "已移除舊的每分鐘排程「$TaskName」（不再閃視窗）。"
} catch { }

# 2. 在「啟動」資料夾建立捷徑：登入後自動啟動、pythonw 無視窗
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup "LINE Outlook Watcher.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pyw
$sc.Arguments = "`"$script`" --serve"
$sc.WorkingDirectory = $repo
$sc.WindowStyle = 7
$sc.Description = "LINE Outlook Watcher (background, no window)"
$sc.Save()
Write-Host "已在啟動資料夾建立捷徑：$lnk"

# 3. 關掉可能還在跑的看守，再於背景啟動一個（無視窗）
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*outlook_daily.py*--serve*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
Start-Process -FilePath $pyw -ArgumentList "`"$script`" --serve" -WorkingDirectory $repo -WindowStyle Hidden

Write-Host ""
Write-Host "看守已在背景啟動（隱形、無視窗、登入後自動）。"
Write-Host "看守記錄：  Get-Content logs\outlook_serve.log -Tail 20"
Write-Host "停用：      刪除「$lnk」，並在工作管理員結束對應的 pythonw"
