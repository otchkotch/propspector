@echo off
setlocal
cd /d "%~dp0\.."
".venv\Scripts\python.exe" "tools\daily_regulatory_review.py" %*
endlocal
