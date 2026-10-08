@echo off
rem ==============================================================================
rem KaraokeZero Desktop Downloader Launcher (Windows)
rem
rem Standalone, zero-config launcher for Windows PCs.
rem Detects required dependencies, assists with installation if missing,
rem and starts the local web interface opening your default browser.
rem ==============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "BIN_DIR=%SCRIPT_DIR%bin"

echo ==========================================================
echo          KaraokeZero Desktop Downloader (Windows)
echo ==========================================================
echo.

rem Add local bin directory to PATH if it exists or create it
if not exist "%BIN_DIR%" (
    mkdir "%BIN_DIR%" >nul 2>&1
)
set "PATH=%BIN_DIR%;%PATH%"

set "MISSING_DEPS=0"

rem ------------------------------------------------------------------------------
rem 1. Check Python 3
rem ------------------------------------------------------------------------------
set "PYTHON_EXEC="
set "PY_VER="

rem Test python
python -c "import sys; sys.exit(0 if sys.version_info.major == 3 else 1)" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXEC=python"
) else (
    rem Test py launcher (py -3)
    py -3 -c "import sys; sys.exit(0 if sys.version_info.major == 3 else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXEC=py"
    ) else (
        rem Test python3
        python3 -c "import sys; sys.exit(0 if sys.version_info.major == 3 else 1)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXEC=python3"
        )
    )
)

if "!PYTHON_EXEC!"=="" (
    echo [ERROR] Python 3 is not installed or not found in system PATH.
    set "MISSING_DEPS=1"
) else (
    if "!PYTHON_EXEC!"=="py" (
        for /f "delims=" %%v in ('py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do set "PY_VER=%%v"
    ) else (
        for /f "delims=" %%v in ('!PYTHON_EXEC! -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do set "PY_VER=%%v"
    )
    echo [OK] Python 3 detected: version !PY_VER!
)

rem ------------------------------------------------------------------------------
rem 2. Check ffmpeg
rem ------------------------------------------------------------------------------
set "FFMPEG_FOUND=0"
where ffmpeg >nul 2>&1
if !errorlevel! equ 0 (
    set "FFMPEG_FOUND=1"
) else (
    if exist "%BIN_DIR%\ffmpeg.exe" (
        set "FFMPEG_FOUND=1"
    )
)

if "!FFMPEG_FOUND!"=="1" (
    echo [OK] ffmpeg detected
) else (
    echo [!] ffmpeg is missing. Video merging and audio conversion require ffmpeg.
    set "MISSING_DEPS=1"
)

rem ------------------------------------------------------------------------------
rem 3. Check yt-dlp (Auto-download standalone binary if missing)
rem ------------------------------------------------------------------------------
set "YTDLP_FOUND=0"
where yt-dlp >nul 2>&1
if !errorlevel! equ 0 (
    set "YTDLP_FOUND=1"
) else (
    if exist "%BIN_DIR%\yt-dlp.exe" (
        set "YTDLP_FOUND=1"
    )
)

if "!YTDLP_FOUND!"=="0" (
    echo [!] yt-dlp was not found in your system PATH.
    echo --^> Attempting to download the official standalone yt-dlp.exe binary...
    set "YT_DLP_URL=https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    set "TARGET_BIN=%BIN_DIR%\yt-dlp.exe"

    rem Try curl first (built into Windows 10/11)
    where curl >nul 2>&1
    if !errorlevel! equ 0 (
        curl.exe -L -s --show-error "!YT_DLP_URL!" -o "!TARGET_BIN!"
    ) else (
        rem Fallback to PowerShell
        powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('!YT_DLP_URL!', '!TARGET_BIN!')"
    )

    if exist "!TARGET_BIN!" (
        echo [OK] Successfully downloaded yt-dlp standalone to !TARGET_BIN!
        set "YTDLP_FOUND=1"
    ) else (
        echo [ERROR] Failed to auto-download yt-dlp.exe.
        set "MISSING_DEPS=1"
    )
) else (
    echo [OK] yt-dlp detected
)

rem ------------------------------------------------------------------------------
rem Dependency Diagnostics & Installation Help
rem ------------------------------------------------------------------------------
if "!MISSING_DEPS!" neq "0" (
    echo.
    echo ==========================================================
    echo [ERROR] Some required dependencies are missing.
    echo ==========================================================
    echo You can install the missing components using Windows Package Manager (winget):
    echo.
    if "!PYTHON_EXEC!"=="" (
        echo   winget install Python.Python.3.11
        echo   (Make sure to check "Add Python to PATH" during installation)
    )
    if "!FFMPEG_FOUND!"=="0" (
        echo   winget install Gyan.FFmpeg
        echo   Or download ffmpeg.exe from https://www.gyan.dev/ffmpeg/builds/ and place in %BIN_DIR%\
    )
    if "!YTDLP_FOUND!"=="0" (
        echo   winget install yt-dlp.yt-dlp
    )
    echo.
    echo After installing, reopen this script.
    echo ==========================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo All dependencies satisfied! Starting Desktop Downloader...
echo Press Ctrl+C at any time in this window to stop the server.
echo ==========================================================
echo.

rem Launch Python backend (which auto-spawns browser)
if "!PYTHON_EXEC!"=="py" (
    py -3 "%SCRIPT_DIR%tools\desktop_downloader\app.py" %*
) else (
    "!PYTHON_EXEC!" "%SCRIPT_DIR%tools\desktop_downloader\app.py" %*
)

exit /b %errorlevel%
