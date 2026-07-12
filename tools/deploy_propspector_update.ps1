param(
    [string]$Version = "",
    [string]$SharedRoot = "L:\CDA software\Feasibility App"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not $Version) {
    $InitPath = Join-Path $ProjectRoot "parcel_packet\__init__.py"
    $VersionMatch = Select-String -Path $InitPath -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($VersionMatch -and $VersionMatch.Matches.Count -gt 0) {
        $Version = $VersionMatch.Matches[0].Groups[1].Value
    }
    else {
        $Version = Get-Date -Format "yyyy.MM.dd.HHmm"
    }
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
$AppExe = Join-Path $ProjectRoot "dist\PropSpector.exe"
$LauncherSource = Join-Path $ProjectRoot "propspector_launcher.py"
$IconPath = Join-Path $ProjectRoot "assets\PropspectorIcon.ico"
$VersionDir = Join-Path $SharedRoot "versions"
$ArchiveDir = Join-Path $SharedRoot "archive"
$VersionedExeName = "PropSpector-$Version.exe"
$VersionedExe = Join-Path $VersionDir $VersionedExeName
$SharedLauncher = Join-Path $SharedRoot "PropSpector.exe"
$SharedIcon = Join-Path $SharedRoot "PropSpector.ico"
$ManifestPath = Join-Path $SharedRoot "PropSpector.update.json"
$LauncherDist = Join-Path $ProjectRoot "dist\launcher"
$LauncherExe = Join-Path $LauncherDist "PropSpector.exe"
$InstallScriptSource = Join-Path $ProjectRoot "tools\install_propspector_shortcut.ps1"
$SharedInstallScript = Join-Path $SharedRoot "Install PropSpector Shortcut.ps1"
$SharedInstallBat = Join-Path $SharedRoot "Install PropSpector Shortcut.bat"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found at $Python"
}

if (-not (Test-Path -LiteralPath $PyInstaller)) {
    throw "PyInstaller not found at $PyInstaller"
}

if (-not (Test-Path -LiteralPath $SharedRoot)) {
    New-Item -ItemType Directory -Path $SharedRoot | Out-Null
}

New-Item -ItemType Directory -Force -Path $VersionDir | Out-Null
New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null

Push-Location $ProjectRoot
try {
    & powershell -ExecutionPolicy Bypass -File ".\build_propspector.ps1"

    if (-not (Test-Path -LiteralPath $AppExe)) {
        throw "Build completed, but the app executable was not found at $AppExe"
    }

    Copy-Item -LiteralPath $AppExe -Destination $VersionedExe -Force

    if (Test-Path -LiteralPath $SharedLauncher) {
        $ArchiveName = "PropSpector-replaced-$(Get-Date -Format 'yyyyMMdd-HHmmss').exe"
        Copy-Item -LiteralPath $SharedLauncher -Destination (Join-Path $ArchiveDir $ArchiveName) -Force
    }

    if (Test-Path -LiteralPath $LauncherDist) {
        Remove-Item -LiteralPath $LauncherDist -Recurse -Force
    }

    & $PyInstaller `
        --noconfirm `
        --onefile `
        --windowed `
        --name "PropSpector" `
        --icon $IconPath `
        --distpath $LauncherDist `
        --workpath (Join-Path $ProjectRoot "build\launcher") `
        --specpath (Join-Path $ProjectRoot "build\launcher") `
        $LauncherSource

    if (-not (Test-Path -LiteralPath $LauncherExe)) {
        throw "Launcher build completed, but the launcher executable was not found at $LauncherExe"
    }

    Copy-Item -LiteralPath $LauncherExe -Destination $SharedLauncher -Force
    Copy-Item -LiteralPath $IconPath -Destination $SharedIcon -Force
    Copy-Item -LiteralPath $InstallScriptSource -Destination $SharedInstallScript -Force

    $InstallBatText = @(
        "@echo off",
        "powershell -NoProfile -ExecutionPolicy Bypass -File ""%~dp0Install PropSpector Shortcut.ps1""",
        "pause"
    ) -join [Environment]::NewLine
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($SharedInstallBat, $InstallBatText, $Utf8NoBom)

    $Manifest = [ordered]@{
        app = "PropSpector"
        latest_version = $Version
        latest_exe = "versions\$VersionedExeName"
        updated_at = (Get-Date).ToString("s")
        update_model = "Desktop shortcuts launch PropSpector.exe, which opens the latest versioned build from this manifest."
    }

    $ManifestJson = $Manifest | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, $Utf8NoBom)

    Write-Host "PropSpector update deployed."
    Write-Host "Launcher: $SharedLauncher"
    Write-Host "Latest app: $VersionedExe"
    Write-Host "Manifest: $ManifestPath"
}
finally {
    Pop-Location
}
