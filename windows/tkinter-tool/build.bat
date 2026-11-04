@echo off
REM ==========================================
REM 双击本文件：把 app.py 打包成 dist\TimeLog.exe
REM 前提：先装好 PyInstaller
REM   py -3 -m pip install pyinstaller
REM ==========================================

REM 让命令行正确显示中文
chcp 65001 >nul

REM 切到本文件所在目录（%~dp0 就是本文件所在路径）
cd /d "%~dp0"

REM 删掉上次的产物，避免新旧文件混在一起
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 开始打包
REM   --noconsole  不弹黑色命令行窗口
REM   --onefile    打成单个 exe
REM   --name       指定产物名
py -3 -m PyInstaller --noconsole --onefile --name TimeLog app.py

REM 失败就停住窗口，方便看报错
if errorlevel 1 (
    echo 打包失败，看上方的报错信息。
    pause
    exit /b 1
)

echo.
echo 完成：dist\TimeLog.exe
pause
