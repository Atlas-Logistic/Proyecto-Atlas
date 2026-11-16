@echo off
setlocal
cd /d "%~dp0"
"C:\Atlas\Proyecto-Atlas\.venv\Scripts\python.exe" -B "%~dp0alta_mobile_lote.py"
echo.
pause
