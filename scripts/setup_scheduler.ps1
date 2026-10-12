<#
.SYNOPSIS
    Registers a disabled-by-default daily Windows scheduled task for MoveInSync Play Store reporting.

.DESCRIPTION
    Creates a Task Scheduler job 'MoveInSync_Daily_Report' that triggers at 06:00 AM daily.
    The task is created in a DISABLED state by default.
    No emails or external webhooks are sent.
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Resolve-Path "$ScriptDir\..").Path
$PythonExe = "$ProjectDir\.venv\Scripts\python.exe"
$ReportScript = "$ProjectDir\run_report.py"

Write-Host "Setting up MoveInSync Scheduled Task..." -ForegroundColor Cyan
Write-Host "Project Dir: $ProjectDir"
Write-Host "Python Path: $PythonExe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment Python not found at $PythonExe. Run setup first."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ReportScript`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At 06:00AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "MoveInSync_Daily_Report" -Action $Action -Trigger $Trigger -Settings $Settings -Description "MoveInSync Play Store daily report runner" -Force | Out-Null
Disable-ScheduledTask -TaskName "MoveInSync_Daily_Report" | Out-Null

Write-Host "`nTask 'MoveInSync_Daily_Report' created successfully!" -ForegroundColor Green
Write-Host "Status: DISABLED (Off by default)" -ForegroundColor Yellow
Write-Host "To enable: Enable-ScheduledTask -TaskName 'MoveInSync_Daily_Report'"
