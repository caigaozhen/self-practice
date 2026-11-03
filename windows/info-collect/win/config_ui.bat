@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem The config window needs no console; use the GUI interpreter to avoid
rem a black window flashing up.

if exist "%~dp0InfoCollect.exe" goto :exe

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0app.py" ui
    goto :eof
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0app.py" ui
    goto :eof
)
py -3 -X utf8 app.py ui
goto :eof

:exe
start "" "%~dp0InfoCollect.exe" ui
