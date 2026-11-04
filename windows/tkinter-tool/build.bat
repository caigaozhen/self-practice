@echo off
REM 双击本文件即可重新打包 exe
REM 产物在 dist\TimeLog.exe

cd /d "%~dp0"

echo [1/2] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/2] 开始打包...
py -3 -m PyInstaller --noconsole --onefile --name TimeLog app.py

if errorlevel 1 (
    echo.
    echo 打包失败，看上面的报错信息。
    pause
    exit /b 1
)

echo.
echo 完成：dist\TimeLog.exe
pause
