@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"

echo Starting InfoCollect (sample mode). Press Ctrl+C to stop.
echo.

%PY% -X utf8 app.py run
if errorlevel 1 (
    echo.
    echo [ERROR] exited with a non-zero code. Python 3.9+ is required.
    pause
)
