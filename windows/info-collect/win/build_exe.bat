@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"

echo ============================================================
echo  Build standalone exe with PyInstaller
echo ============================================================
echo.

%PY% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [MISSING] PyInstaller not found.
    echo.
    echo Install it first ^(only needed for building, the app itself has no deps^):
    echo     %PY% -m pip install pyinstaller
    echo.
    pause
    exit /b 1
)

echo Building, the first run takes a while...
echo.

echo [1/2] Generating version resource (single source: config.APP_VERSION)...
%PY% -X utf8 make_version_info.py
if errorlevel 1 (
    echo [FAILED] Could not generate version_info.txt.
    pause
    exit /b 1
)
echo.

rem ---- why these flags ----
rem  --onedir     one folder instead of a single exe.
rem               Do NOT use --onefile for a resident app: it unpacks to a temp
rem               dir on every start (1-3s slower) and antivirus likes to flag it.
rem  --windowed   no console allocated (same as running under pythonw).
rem               Double-clicking the exe goes straight to tray mode.
rem  --add-data   bundle the icon; the app looks for it next to the exe.
rem  --version-file  makes the version show up in exe Properties -> Details.
echo [2/2] Running PyInstaller...
%PY% -m PyInstaller ^
    --noconfirm --clean ^
    --onedir ^
    --windowed ^
    --name InfoCollect ^
    --icon "infocollect.ico" ^
    --add-data "infocollect.ico;." ^
    --version-file "version_info.txt" ^
    app.py

if errorlevel 1 (
    echo.
    echo [FAILED] Build error, see the log above.
    echo          If PyInstaller does not support your Python version yet,
    echo          try building with Python 3.12 / 3.13 -- no code changes needed.
    pause
    exit /b 1
)

rem PyInstaller 6 puts --add-data files under _internal, but the app looks for
rem the icon next to the exe; copy it to the root so a fresh build works too.
copy /y "infocollect.ico" "dist\InfoCollect\" >nul

for %%f in (start_silent.bat stop.bat config_ui.bat report.bat install_autostart.bat uninstall_autostart.bat) do (
    if exist "%%f" copy /y "%%f" "dist\InfoCollect\" >nul
)

echo.
echo ============================================================
echo  Build finished
echo ============================================================
echo  Output : %CD%\dist\InfoCollect\
echo  Program: InfoCollect.exe
echo.
echo  To distribute: copy the whole dist\InfoCollect folder.
echo                 The target machine does not need Python.
echo.
echo  To verify: double-click InfoCollect.exe, a tray icon appears.
echo             Then open the config window and tick "autostart".
echo.
pause
