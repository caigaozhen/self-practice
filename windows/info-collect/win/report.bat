@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

rem The packaged exe is a GUI app: it has no console to print into,
rem so "report --window" opens the report window instead.
if exist "%~dp0InfoCollect.exe" goto :exe

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"

%PY% -X utf8 app.py report
echo.
pause
goto :eof

:exe
start "" "%~dp0InfoCollect.exe" report --window
