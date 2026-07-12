$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "tools\daily_regulatory_review.py"
$TaskName = "PropSpector Daily Regulatory Review"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found at $Python"
}

if (-not (Test-Path -LiteralPath $Script)) {
    throw "Daily review script not found at $Script"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:30AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs PropSpector's daily regulatory interpretation review and writes a dated wiki report." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Daily report folder: $(Join-Path $Root 'wiki\daily-reviews')"
