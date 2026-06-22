@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=FH6Auto"
set "MAIN_FILE=main.py"
set "VERSION=unknown"

for /f "tokens=2 delims=:," %%v in ('findstr /i /c:"\"version\"" "version.json"') do (
    set "VERSION=%%~v"
)
set "VERSION=%VERSION: =%"
set "VERSION=%VERSION:"=%"

set "BUILD_NAME=%APP_NAME%_v%VERSION%"
set "DIST_EXE=%BUILD_NAME%.exe"

echo.
echo ==============================
echo Building %APP_NAME%
echo ==============================
echo Version: %VERSION%
echo Output : dist\%DIST_EXE%
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found in PATH.
    pause
    exit /b 1
)

echo [1/3] Cleaning old files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%BUILD_NAME%.spec" del /f /q "%BUILD_NAME%.spec"
if exist "%APP_NAME%.spec" del /f /q "%APP_NAME%.spec"

echo [2/3] Running PyInstaller...
python -m PyInstaller ^
    -n "%BUILD_NAME%" ^
    -F ^
    -w ^
    --uac-admin ^
    "%MAIN_FILE%" ^
    --icon=assets/icon.ico ^
    --add-data "images;images" ^
    --add-data "assets;assets"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Build complete.
echo Output file: dist\%DIST_EXE%
echo.
pause
