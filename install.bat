@echo off
chcp 65001 > nul
echo ========================================
echo   Installing...
echo ========================================
echo.

call :ensure_uv
if %errorlevel% neq 0 exit /b %errorlevel%

set "UV_SYNC_ARGS=--python 3.11"
set "NEEDS_ASR=0"
set "NEEDS_GIT=0"

:parse_args
if "%~1"=="" goto after_parse_args
if /I "%~1"=="--with-asr" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra asr"
    set "NEEDS_ASR=1"
    shift
    goto parse_args
)
if /I "%~1"=="--asr" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra asr"
    set "NEEDS_ASR=1"
    shift
    goto parse_args
)
if /I "%~1"=="--with-video" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra video"
    shift
    goto parse_args
)
if /I "%~1"=="--video" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra video"
    shift
    goto parse_args
)
if /I "%~1"=="--with-background-removal" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra background-removal"
    shift
    goto parse_args
)
if /I "%~1"=="--background-removal" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra background-removal"
    shift
    goto parse_args
)
if /I "%~1"=="--with-hermes" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra hermes"
    set "NEEDS_GIT=1"
    shift
    goto parse_args
)
if /I "%~1"=="--hermes" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra hermes"
    set "NEEDS_GIT=1"
    shift
    goto parse_args
)
if /I "%~1"=="--full" (
    set "UV_SYNC_ARGS=%UV_SYNC_ARGS% --extra full"
    set "NEEDS_ASR=1"
    shift
    goto parse_args
)
echo Unknown option: %~1
echo Supported options: --with-asr --with-video --with-background-removal --with-hermes --full
pause
exit /b 1

:after_parse_args

if "%NEEDS_GIT%"=="1" (
    where git > nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: Git not found in PATH
        echo Git is only required when installing the local Hermes Agent package into this environment.
        echo Install Git for Windows first: https://git-scm.com/download/win
        pause
        exit /b 1
    )
)

REM PyAudio ships wheels for common Windows x64/x86 Python builds.
REM Other Windows architectures may need extra native build tools.
if "%NEEDS_ASR%"=="1" if /I not "%PROCESSOR_ARCHITECTURE%"=="AMD64" if /I not "%PROCESSOR_ARCHITEW6432%"=="AMD64" if /I not "%PROCESSOR_ARCHITECTURE%"=="x86" (
    echo Warning: Windows architecture %PROCESSOR_ARCHITECTURE% may not have a PyAudio wheel.
    echo If PyAudio falls back to source build, use Windows x64 or install Microsoft C++ Build Tools.
    echo.
)

echo Installing dependencies...
echo.

uv sync %UV_SYNC_ARGS%

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
exit /b 0

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
