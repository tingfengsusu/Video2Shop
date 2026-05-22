@echo off
setlocal enabledelayedexpansion

REM ================================================================
REM  Video2Shop — PyInstaller Build Script
REM
REM  Usage:
REM    scripts\build.bat              (uses version from src\version.py)
REM    scripts\build.bat 1.0.1        (overrides version)
REM
REM  Output:
REM    dist\Video2Shop\               (onedir folder)
REM    Video2Shop_v<version>.zip      (zipped for distribution)
REM
REM  Note: EasyOCR models (~100MB) are NOT bundled.
REM        They auto-download to ~/.EasyOCR on first run.
REM ================================================================

REM Step 0: change to project root (this script lives in scripts/)
cd /d "%~dp0.."
set PROJECT_ROOT=%cd%

echo ============================================================
echo   Video2Shop — PyInstaller Build
echo ============================================================
echo.

REM -- Resolve version: arg > src/version.py > fallback "1.0.0" --
if not "%~1"=="" (
    set APP_VERSION=%~1
    echo Version: !APP_VERSION! (from command line)
) else (
    REM Try to read __version__ from src/version.py
    for /f "tokens=2 delims== " %%v in (
        'python -c "exec(open(r'src\version.py', encoding='utf-8').read()); print(__version__)" 2^>nul'
    ) do set APP_VERSION=%%v
    REM Strip quotes
    set APP_VERSION=!APP_VERSION:"=!
    if "!APP_VERSION!"=="" set APP_VERSION=1.0.0
    echo Version: !APP_VERSION! (from src\version.py)
)

echo.

REM ---- check pyinstaller ----------------------------------------
pip show pyinstaller >nul 2>&1
if !errorlevel! neq 0 (
    echo [1/6] Installing pyinstaller...
    pip install pyinstaller
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install pyinstaller.
        pause
        exit /b 1
    )
)

REM ---- check UPX ------------------------------------------------
echo [1/6] Checking UPX...
set UPX_DIR=
where upx >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%i in ('where upx') do set UPX_DIR=%%~dpi
    echo   UPX found: !UPX_DIR!
) else if exist "tools\upx.exe" (
    set UPX_DIR=%PROJECT_ROOT%\tools
    echo   UPX found: tools\upx.exe
) else (
    echo   UPX not found — build without compression.
    echo   To enable: download upx.exe from https://upx.github.io/ and put it in tools\ or PATH.
)

REM ---- clean old artifacts --------------------------------------
echo [2/6] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist "Video2Shop_v*.zip" del /q "Video2Shop_v*.zip" 2>nul
if exist "Video2Shop_v*.exe" del /q "Video2Shop_v*.exe" 2>nul
echo   Done.

REM ---- run pyinstaller ------------------------------------------
echo [3/6] Running PyInstaller (--onedir)...

if not "!UPX_DIR!"=="" (
    set UPX_FLAG=--upx-dir="!UPX_DIR!"
) else (
    set UPX_FLAG=
)

pyinstaller ^
    --onedir ^
    --noconsole ^
    --name="Video2Shop" ^
    !UPX_FLAG! ^
    --add-data="config\config.default.yaml;config" ^
    --add-data="resources\templates;resources\templates" ^
    --add-data="tools\ffmpeg.exe;tools" ^
    --hidden-import=yaml ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=cv2 ^
    --hidden-import=numpy ^
    --hidden-import=easyocr ^
    --hidden-import=playwright ^
    --hidden-import=playwright.sync_api ^
    --hidden-import=requests ^
    --hidden-import=pipeline ^
    --hidden-import=video_processor ^
    --hidden-import=deepseek_web_analyzer ^
    --hidden-import=shopping_platform ^
    --hidden-import=web_interface ^
    --hidden-import=recipe_extractor ^
    --hidden-import=bili_downloader ^
    --hidden-import=ttkbootstrap ^
    --hidden-import=version ^
    --collect-all=ttkbootstrap ^
    --exclude-module=flask ^
    --exclude-module=jinja2 ^
    --exclude-module=werkzeug ^
    --exclude-module=markupsafe ^
    --exclude-module=itsdangerous ^
    --exclude-module=blinker ^
    --exclude-module=click ^
    src\gui.py

if !errorlevel! neq 0 (
    echo.
    echo ============================================================
    echo   [ERROR] PyInstaller build failed!
    echo ============================================================
    echo.
    echo   Common issues:
    echo     - Missing dependencies: pip install -r requirements.txt
    echo     - Conflicting packages:  pip install --upgrade pyinstaller
    echo     - Missing files: ensure src\gui.py and config\ exist
    echo.
    pause
    exit /b 1
)

REM ---- verify output --------------------------------------------
echo [4/6] Verifying output...
if not exist "dist\Video2Shop\Video2Shop.exe" (
    echo [ERROR] dist\Video2Shop\Video2Shop.exe was not generated.
    pause
    exit /b 1
)

for %%A in ("dist\Video2Shop\Video2Shop.exe") do set EXE_SIZE=%%~zA
set /a EXE_SIZE_MB=!EXE_SIZE! / 1048576
echo   OK: dist\Video2Shop\Video2Shop.exe (!EXE_SIZE_MB! MB)

REM ---- zip for distribution -------------------------------------
echo [5/6] Creating distribution zip...
set ZIP_NAME=Video2Shop_v!APP_VERSION!.zip
powershell -Command "Compress-Archive -Path 'dist\Video2Shop\*' -DestinationPath '!ZIP_NAME!' -Force"
if !errorlevel! equ 0 (
    echo   Created: !ZIP_NAME!
) else (
    echo [WARN] Could not create zip.
)

REM ---- clean pyinstaller work files -----------------------------
echo [6/6] Cleaning PyInstaller work files...
if exist build rmdir /s /q build
if exist "Video2Shop.spec" del /q "Video2Shop.spec" 2>nul
echo   Done.

REM ---- done -----------------------------------------------------
echo.
echo ============================================================
echo   Build complete!
echo ============================================================
echo.
echo   Version:  !APP_VERSION!
echo   Output:   dist\Video2Shop\
echo   Zip:      !ZIP_NAME!
echo.
echo   Note: EasyOCR models (~100MB) will download on first run.
echo   For installer build, see: scripts\setup.iss
echo.
pause
