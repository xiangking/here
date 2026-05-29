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

REM Git is required because pyproject.toml uses git dependencies.
where git > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Git not found in PATH
    echo Install Git for Windows first: https://git-scm.com/download/win
    pause
    exit /b 1
)

REM PyAudio ships wheels for common Windows x64/x86 Python builds.
REM Other Windows architectures may need extra native build tools.
if /I not "%PROCESSOR_ARCHITECTURE%"=="AMD64" if /I not "%PROCESSOR_ARCHITEW6432%"=="AMD64" if /I not "%PROCESSOR_ARCHITECTURE%"=="x86" (
    echo Warning: Windows architecture %PROCESSOR_ARCHITECTURE% may not have a PyAudio wheel.
    echo If PyAudio falls back to source build, use Windows x64 or install Microsoft C++ Build Tools.
    echo.
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
