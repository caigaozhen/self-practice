@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem ============================================================
rem  Start InfoCollect in tray mode (no console window).
rem
rem  Works in both shapes:
rem    * packaged  : InfoCollect.exe sits next to this file
rem    * source    : app.py + a local Python
rem
rem  Python vs pythonw: the only difference is the PE header
rem  Subsystem field. python.exe is a console app (black window),
rem  pythonw.exe is a GUI app (no window) -- that is why the
rem  launcher must be pythonw, otherwise every boot flashes a
rem  console window.
rem ============================================================

echo Starting InfoCollect (tray mode)...
echo.

if exist "%~dp0InfoCollect.exe" goto :exe

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0app.py" tray
    goto :check
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0app.py" tray
    goto :check
)

echo [WARN] pythonw/pyw not found, falling back to console mode.
echo        Keep this window open, closing it stops collection.
echo.
py -3 -X utf8 app.py tray
goto :eof

:exe
start "" "%~dp0InfoCollect.exe" tray
goto :check

:check
rem Single-instance mutex makes repeated double-clicks harmless.
timeout /t 2 >nul
echo Done. Look for the tray icon near the clock (maybe under the ^ arrow).
echo Right-click it for the menu, double-click for today's report.
timeout /t 3 >nul
