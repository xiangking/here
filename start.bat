@echo off
chcp 65001 > nul

cd /d "%~dp0"

:: Check that the current path contains only ASCII characters
powershell -Command "if ('%cd%' -match '[^\x20-\x7E]') { Write-Host 'Error: The current path contains non-ASCII characters (e.g. Chinese, Japanese).'; Write-Host 'Please move the folder to a path with only English characters, e.g. D:\here'; Write-Host 'Current path: %cd%'; exit 1 } else { exit 0 }" > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo   Path contains non-ASCII characters!
    echo   Please move this folder to a path
    echo   with only English letters and numbers.
    echo   e.g. D:\here
    echo ========================================
    echo   Current: %cd%
    echo ========================================
    pause
    exit /b 1
)

:: Check for embedded python, fall back to uv-managed source environment
if exist "runtime\python.exe" (
    set "PYTHON_EXE=runtime\python.exe"
    set "HERE_PROJECT_ROOT=%cd%"
    if "%HERE_APP_HOME%"=="" set "HERE_APP_HOME=%APPDATA%\here"
) else (
    call :ensure_uv
    if %errorlevel% neq 0 exit /b %errorlevel%
    uv run python -m app.desktop.main
    pause
    exit /b %errorlevel%
)

%PYTHON_EXE% -m app.desktop.main
pause
exit /b %errorlevel%

:ensure_uv
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv > nul 2>&1
if %errorlevel% equ 0 exit /b 0

echo uv not found. Installing uv...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if %errorlevel% neq 0 (
    echo Error: uv installation failed.
    echo Install uv manually: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

where uv > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: uv installation finished, but uv is still not available in PATH.
    echo Try opening a new terminal, or add %%USERPROFILE%%\.local\bin to PATH.
    pause
    exit /b 1
)
exit /b 0
