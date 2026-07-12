@echo off
setlocal
cd /d "%~dp0\.."
".venv\Scripts\python.exe" "tools\municipal_code_discovery.py" %*
endlocal
