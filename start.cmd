@echo off
setlocal
cd /d "%~dp0"
python app.py --port 18080
endlocal
