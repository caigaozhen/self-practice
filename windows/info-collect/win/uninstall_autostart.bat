@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ============================================================
echo  Remove autostart
echo ============================================================
echo.

if exist "%~dp0InfoCollect.exe" goto :exe

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"
%PY% -X utf8 app.py autostart off
goto :tail

:exe
"%~dp0InfoCollect.exe" autostart off
if errorlevel 1 (
    echo [FAILED] see %%APPDATA%%\InfoCollect\infocollect.log
) else (
    echo Done. It will no longer start with Windows.
)

:tail
echo.
pause
