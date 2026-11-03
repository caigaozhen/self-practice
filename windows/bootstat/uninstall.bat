@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo Removing BootStat autostart...
echo.

py -3 bootstat.py --uninstall 2>nul
if errorlevel 1 python bootstat.py --uninstall

echo.
echo The data file stays at %%LOCALAPPDATA%%\BootStat\boots.json - delete it manually if you want a clean slate.
echo.
pause
