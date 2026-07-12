$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "tools\municipal_bot_learning.py"
$TaskName = "PropSpector Municipal Bot Learning"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found at $Python"
}

if (-not (Test-Path -LiteralPath $Script)) {
    throw "Municipal bot learning script not found at $Script"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Triggers = @(
    New-ScheduledTaskTrigger -Daily -At 8:00AM
    New-ScheduledTaskTrigger -Daily -At 10:00AM
    New-ScheduledTaskTrigger -Daily -At 12:00PM
    New-ScheduledTaskTrigger -Daily -At 2:00PM
    New-ScheduledTaskTrigger -Daily -At 4:00PM
    New-ScheduledTaskTrigger -Daily -At 6:00PM
)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "Runs low-frequency PropSpector municipal bot learning and writes cached source-status reports." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Learning report folder: $(Join-Path $Root 'wiki\municipal-learning')"
