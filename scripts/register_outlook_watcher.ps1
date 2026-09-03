#!/usr/bin/env pwsh
# 建立「登入後常駐」的 Outlook 看守排程：你在 LINE 傳「Outlook 信件」即可觸發讀取。
# 與每日 07:00 的 LINE Outlook Daily 是兩個獨立排程。
#
# 用法：pwsh scripts/register_outlook_watcher.ps1

param([string]$TaskName = "LINE Outlook Watcher")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$cmd = Join-Path $repo "scripts\run_outlook_serve.cmd"
if (-not (Test-Path $cmd)) { Write-Error "找不到 $cmd" }

$action = New-ScheduledTaskAction -Execute $cmd
$trigger = New-ScheduledTaskTrigger -AtLogOn
# 互動、非提權（與 Outlook 同層級）。掛掉自動重啟。
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "已建立常駐看守「$TaskName」（登入後自動啟動）。"
Write-Host "現在先手動啟動一次：  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "看守記錄：            Get-Content logs\outlook_serve.log -Tail 20"
Write-Host "停用：                Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
