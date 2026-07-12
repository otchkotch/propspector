$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "tools\municipal_code_discovery.py"
$TaskName = "PropSpector Municipal Code Discovery"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found at $Python"
}

if (-not (Test-Path -LiteralPath $Script)) {
    throw "Municipal code discovery script not found at $Script"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Discovers NCC municipality code-source candidates for PropSpector jurisdiction bots." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Discovery report folder: $(Join-Path $Root 'wiki\municipal-discovery')"
