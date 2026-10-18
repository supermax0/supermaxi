param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$DailyAt = "02:00",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30,
    [string]$TaskName = "Finora Daily Database Backup"
)

$ErrorActionPreference = "Stop"
$backupScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "backup_server_database.ps1")).Path
$powershell = (Get-Command powershell.exe).Source
$argument = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -RetentionDays {1}' -f `
    $backupScript, $RetentionDays
$action = New-ScheduledTaskAction -Execute $powershell -Argument $argument
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($DailyAt, "HH:mm", $null))
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "تنزيل نسخة احتياطية يومية من سيرفر Finora إلى اللابتوب" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Output ("TASK_OK name={0} state={1} next={2}" -f $task.TaskName, $task.State, $taskInfo.NextRunTime)
