@echo off
REM
REM Planify CLI - Windows 启动脚本
REM 用于在任意工作目录中启动 Planify REPL。
REM 用户只需 cd 到工作目录，然后执行此脚本即可。
REM

REM Save current directory
set SAVED_CD=%CD%

REM Get script directory and parent (planify root)
cd /d "%~dp0"
set PLANIFY_ROOT=%cd%
cd /d "%PLANIFY_ROOT%"

echo ========================================
echo Planify CLI - Single User Mode
echo ========================================
echo Work Directory: %SAVED_CD%
echo Planify Root: %PLANIFY_ROOT%
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    python3 --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo Error: Python or python3 not found
        pause
        exit /b 1
    )
    set PYTHON_CMD=python3
) else (
    set PYTHON_CMD=python
)

echo Using Python: %PYTHON_CMD%
echo.

REM Set PYTHONPATH and run cli.py
set PYTHONPATH=%PLANIFY_ROOT%;%PYTHONPATH%

python cli.py

REM Pause on error
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Program exited with error code: %ERRORLEVEL%
    pause
)
