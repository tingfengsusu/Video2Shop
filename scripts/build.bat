@echo off
setlocal enabledelayedexpansion

REM ================================================================
REM  Video2Shop ¡ª PyInstaller Build Script
REM
REM  Usage:
REM    scripts\build.bat              (uses version from src\version.py)
REM    scripts\build.bat 1.0.1        (overrides version)
REM
REM  Output:
REM    dist\Video2Shop.exe
REM    Video2Shop_v<version>.exe      (copied to project root)
REM ================================================================

REM Step 0: change to project root (this script lives in scripts/)
cd /d "%~dp0.."
set PROJECT_ROOT=%cd%

echo ============================================================
echo   Video2Shop ¡ª PyInstaller Build
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
    echo [1/5] Installing pyinstaller...
    pip install pyinstaller
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install pyinstaller.
        pause
        exit /b 1
    )
)

REM ---- clean old artifacts --------------------------------------
echo [1/5] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist "Video2Shop_v*.exe" del /q "Video2Shop_v*.exe" 2>nul
echo   Done.

REM ---- run pyinstaller ------------------------------------------
echo [2/5] Running PyInstaller...

pyinstaller ^
    --onefile ^
    --noconsole ^
    --name="Video2Shop" ^
    --add-data="config\config.default.yaml;config" ^
    --add-data="resources\templates;resources\templates" ^
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
    --hidden-import=static_ffmpeg ^
    --hidden-import=version ^
    --collect-all=easyocr ^
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
echo [3/5] Verifying output...
if not exist "dist\Video2Shop.exe" (
    echo [ERROR] dist\Video2Shop.exe was not generated.
    pause
    exit /b 1
)

for %%A in ("dist\Video2Shop.exe") do set EXE_SIZE=%%~zA
set /a EXE_SIZE_MB=!EXE_SIZE! / 1048576
echo   OK: dist\Video2Shop.exe (!EXE_SIZE_MB! MB)

REM ---- copy to root with version stamp --------------------------
echo [4/5] Copying EXE to project root...
set OUTPUT_NAME=Video2Shop_v!APP_VERSION!.exe
copy /y "dist\Video2Shop.exe" "!OUTPUT_NAME!" >nul
if !errorlevel! equ 0 (
    echo   Copied: !OUTPUT_NAME!
) else (
    echo [WARN] Could not copy to root.
)

REM ---- clean pyinstaller work files -----------------------------
echo [5/5] Cleaning PyInstaller work files...
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
echo   Output:   dist\Video2Shop.exe
echo   Copy:     !OUTPUT_NAME!
echo.
echo   Next steps:
echo     1. Test the EXE in a clean environment
echo     2. Check for missing resources at runtime
echo     3. Follow RELEASE.md to publish to GitHub
echo.
pause
