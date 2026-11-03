@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo Asking InfoCollect to exit (it closes the open session and pushes pending data)...
echo.

if exist "%~dp0InfoCollect.exe" goto :exe

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"
%PY% -X utf8 app.py stop
goto :tail

:exe
rem The exe is windowed and prints nothing; the .bat narrates instead.
"%~dp0InfoCollect.exe" stop
if errorlevel 1 (
    echo Nothing to stop -- it was not running.
) else (
    echo Exit request sent.
)

:tail
timeout /t 3 >nul
echo.
pause
