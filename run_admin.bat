@echo off
:: FH6Auto by YSTO | Deep Optimized by SArB1e Launcher - 请求管理员权限后启动应用
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo 正在请求管理员权限...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
cd /d "%~dp0"
echo FH6Auto by YSTO ^| Deep Optimized by SArB1e 启动中...
start "" "C:\Program Files\Python310\python.exe" "%~dp0main.py"
exit
