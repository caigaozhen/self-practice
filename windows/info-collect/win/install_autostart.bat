@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ============================================================
echo  Install autostart (current user only, no admin needed)
echo ============================================================
echo.

if exist "%~dp0InfoCollect.exe" goto :exe

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"
%PY% -X utf8 app.py autostart on
goto :tail

:exe
rem Windowed exe prints nothing, so report progress from the .bat itself.
"%~dp0InfoCollect.exe" autostart on
if errorlevel 1 (
    echo [FAILED] see %%APPDATA%%\InfoCollect\infocollect.log
) else (
    echo Done. It will start with Windows from now on.
    echo Verify or undo it in the config window (config_ui.bat).
)

:tail
echo.
echo To remove it later: run uninstall_autostart.bat
echo.
pause
