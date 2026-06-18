@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set APP_NAME=FH6AutoStableVersion By SArB1e
set MAIN_FILE=main.py

echo.
echo ==============================
echo 开始打包 %APP_NAME% by YSTO ^| Deep Optimized by SArB1e
echo ==============================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先配置环境变量
    pause
    exit /b 1
)

echo [1/3] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%APP_NAME%.spec" del /f /q "%APP_NAME%.spec"

echo [2/3] 执行 PyInstaller...
python -m PyInstaller ^
    -n "%APP_NAME%" ^
    -F ^
    -w ^
    --uac-admin ^
    "%MAIN_FILE%" ^
    --icon=assets/icon.ico ^
    --add-data "images;images" ^
    --add-data "assets;assets"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo 输出目录: dist\%APP_NAME%.exe
echo.
pause
