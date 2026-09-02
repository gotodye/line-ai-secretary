#!/usr/bin/env pwsh
# 建立每日 Outlook 讀信的 Windows 排程。
# 重點：以「互動、非系統管理員」身分執行 —— 這樣才和 Outlook 同一個權限層級，
# COM 才連得上（提升權限反而會失敗）。需要你當天已登入、Outlook 開著。
#
# 用法：
#   pwsh scripts/register_outlook_task.ps1              # 預設每天 07:00
#   pwsh scripts/register_outlook_task.ps1 -Time 06:50  # 自訂時間

param(
    [string]$Time = "07:00",
    [string]$TaskName = "LINE Outlook Daily"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$cmd = Join-Path $repo "scripts\run_outlook_daily.cmd"
if (-not (Test-Path $cmd)) { Write-Error "找不到 $cmd" }

$action = New-ScheduledTaskAction -Execute $cmd
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# Interactive + Limited：跟 Outlook 同層級，非提升權限。
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "已建立每日排程「$TaskName」，每天 $Time 執行。"
Write-Host "（需你已登入 Windows、且傳統版 Outlook 開著。PC 關機那天不會跑。）"
Write-Host ""
Write-Host "立即手動測一次：  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "查看執行結果：    Get-Content logs\outlook_daily.log -Tail 30"
Write-Host "移除排程：        Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
