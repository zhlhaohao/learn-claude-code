@echo off
REM Planify 启动脚本 (Windows)

echo ================================================
echo   Planify - 交互式代理系统
echo ================================================
echo.

"C:\Users\lianghao\AppData\Local\Programs\Python\Python310\python.exe" "%~dp0backend\app\run.py"

if errorlevel 1 (
    echo.
    echo 启动失败，请检查错误信息。
    pause
)
