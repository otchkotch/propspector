param(
    [string]$SharedRoot = "L:\CDA software\Feasibility App",
    [string]$ShortcutName = "PropSpector"
)

$ErrorActionPreference = "Stop"

$Launcher = Join-Path $SharedRoot "PropSpector.exe"
$Icon = Join-Path $SharedRoot "PropSpector.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "$ShortcutName.lnk"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "PropSpector launcher was not found at $Launcher"
}

if (-not (Test-Path -LiteralPath $Icon)) {
    throw "PropSpector icon was not found at $Icon"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $SharedRoot
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = "Launch PropSpector"
$Shortcut.Save()

Write-Host "Installed desktop shortcut: $ShortcutPath"
