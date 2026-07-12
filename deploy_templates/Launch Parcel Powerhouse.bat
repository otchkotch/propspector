@echo off
setlocal
cd /d "%~dp0ParcelPowerhouse"

if not exist ".venv\Scripts\pythonw.exe" (
    powershell -ExecutionPolicy Bypass -File "Setup Parcel Powerhouse.ps1"
)

start "" ".venv\Scripts\pythonw.exe" "powerhouse_main.py"
