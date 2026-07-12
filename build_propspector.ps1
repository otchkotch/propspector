$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements_environmental_widget.txt

.\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --onefile `
    --windowed `
    --name "PropSpector" `
    --icon "assets\PropspectorIcon.ico" `
    --add-data "assets;assets" `
    --add-data "parcel_packet\assets;parcel_packet\assets" `
    --add-data "cache\municipal-sections;cache\municipal-sections" `
    --add-data "cache\municipal-source-status;cache\municipal-source-status" `
    propspector_main.py

Write-Host "Built: dist\PropSpector.exe"
