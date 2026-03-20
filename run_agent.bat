@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo.
echo 🚀 运行 Agent (UTF-8 模式)...
echo.

if "%1"=="s02" (
    goto run_s02
) else if "%1"=="s_full" (
    goto run_s_full
) else if "%1"=="" (
    echo 请指定 Agent: run_agent.bat s02 或 run_agent.bat s_full
    echo.
    echo 例如:
    echo   run_agent.bat s02
    echo   run_agent.bat s_full
    goto end
)

:run_s02
python run_agent_utf8.py s02
goto end

:run_s_full
python run_agent_utf8.py s_full
goto end

:end
pause