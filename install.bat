@echo off
chcp 65001 > nul
echo ========================================
echo   Installing...
echo ========================================
echo.

REM Check if uv exists
where uv > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: uv not found in PATH
    echo Install uv first: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo Installing dependencies...
echo.

uv sync --python 3.11

REM Check if installation succeeded
if %errorlevel% neq 0 (
    echo.
    echo Error occurred during dependency installation
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo You can now run start.bat to launch the application
pause
