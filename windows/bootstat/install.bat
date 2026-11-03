@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo Installing BootStat autostart...
echo.

py -3 bootstat.py --install 2>nul
if errorlevel 1 (
    python bootstat.py --install
    if errorlevel 1 (
        echo.
        echo [ERROR] Python not found. Install Python from https://www.python.org/downloads/
        echo         Remember to tick "Add python.exe to PATH" during setup.
    )
)

echo.
pause
