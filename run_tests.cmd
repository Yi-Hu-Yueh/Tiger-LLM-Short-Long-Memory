@echo off
setlocal
cd /d "%~dp0"
python -W error::ResourceWarning -m unittest -v test_app.py
endlocal
