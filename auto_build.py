#!/usr/bin/env python3
"""
Video2Shop — One-Click Auto Build Script
=========================================
Double-click to build Video2Shop.exe with zero manual steps.

What it does:
  1. Reads version from src/version.py
  2. Checks / installs PyInstaller
  3. Cleans old build artifacts
  4. Runs PyInstaller (same params as scripts/build.bat)
  5. Verifies dist/Video2Shop.exe
  6. Copies to root as Video2Shop_v{version}.exe
  7. Prints a friendly success / failure summary

Usage:
    python auto_build.py           # build
    python auto_build.py --clean   # clean only, no build
    python auto_build.py --keep    # keep build/ and .spec after build
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).resolve().parent
VERSION_FILE = SCRIPT_DIR / "src" / "version.py"
EXE_SOURCE   = SCRIPT_DIR / "dist" / "Video2Shop.exe"

# PyInstaller parameters — keep in sync with scripts/build.bat
ENTRY_POINT      = "src" + os.sep + "gui.py"
OUTPUT_NAME      = "Video2Shop"

HIDDEN_IMPORTS = [
    "yaml", "PIL", "PIL.Image", "cv2", "numpy", "easyocr",
    "playwright", "playwright.sync_api", "requests",
    "pipeline", "video_processor", "deepseek_web_analyzer",
    "shopping_platform", "web_interface", "recipe_extractor",
    "bili_downloader", "ttkbootstrap", "static_ffmpeg",
    "version",
]

COLLECT_ALL = ["easyocr", "ttkbootstrap"]

EXCLUDE_MODULES = [
    "flask", "jinja2", "werkzeug", "markupsafe",
    "itsdangerous", "blinker", "click",
]

# --add-data pairs: (source, dest)
ADD_DATA = [
    ("config" + os.sep + "config.default.yaml", "config"),
    ("resources" + os.sep + "templates", "resources" + os.sep + "templates"),
]

MIN_PYTHON = (3, 8)


# ── ANSI color helpers (no external deps) ─────────────────────────────────

class Style:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"

    @staticmethod
    def _enable():
        # Disable colors if piped or on old Windows without ANSI support
        if not sys.stdout.isatty():
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass
        return True

    _ON = _enable.__func__()  # call once at import time

    @classmethod
    def _apply(cls, code: str, text: str) -> str:
        return f"{code}{text}{cls.RESET}" if cls._ON else text

    @classmethod
    def bold(cls, text: str) -> str:     return cls._apply(cls.BOLD, text)
    @classmethod
    def green(cls, text: str) -> str:    return cls._apply(cls.GREEN, text)
    @classmethod
    def red(cls, text: str) -> str:      return cls._apply(cls.RED, text)
    @classmethod
    def yellow(cls, text: str) -> str:   return cls._apply(cls.YELLOW, text)
    @classmethod
    def cyan(cls, text: str) -> str:     return cls._apply(cls.CYAN, text)
    @classmethod
    def dim(cls, text: str) -> str:      return cls._apply(cls.DIM, text)
    @classmethod
    def header(cls, text: str) -> str:   return cls._apply(cls.BOLD + cls.CYAN, text)


# ── Helpers ────────────────────────────────────────────────────────────────

def print_header(text: str):
    print()
    print(Style.bold(f"  {text}"))
    print(Style.dim(f"  {'─' * 58}"))


def print_ok(text: str):
    print(f"  {Style.green('OK:')} {text}")


def print_err(text: str):
    print(f"  {Style.red('ERROR:')} {text}")


def print_warn(text: str):
    print(f"  {Style.yellow('WARN:')} {text}")


def print_info(text: str):
    print(f"  {Style.cyan('INFO:')} {text}")


def confirm_exit():
    """Pause before exit so the user can read output (double-click friendly)."""
    print()
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


def fmt_size(bytes_: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"


# ── Steps ──────────────────────────────────────────────────────────────────

def check_python() -> bool:
    print_header("Checking Python version")
    v = sys.version_info[:2]
    vs = f"{v[0]}.{v[1]}"
    if v >= MIN_PYTHON:
        print_ok(f"Python {vs}")
        return True
    print_err(f"Python {vs} is too old (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
    return False


def read_version() -> str:
    print_header("Reading version")
    if not VERSION_FILE.exists():
        print_warn(f"{VERSION_FILE} not found, defaulting to 1.0.0")
        return "1.0.0"
    content = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    v = m.group(1) if m else "1.0.0"
    print_ok(f"Version: {v}")
    return v


def ensure_pyinstaller() -> bool:
    print_header("Checking PyInstaller")
    try:
        import PyInstaller
        print_ok("PyInstaller already installed")
        return True
    except ImportError:
        pass

    print_info("Installing PyInstaller...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        cwd=str(SCRIPT_DIR),
    )
    if r.returncode != 0:
        print_err("Failed to install PyInstaller")
        return False
    print_ok("PyInstaller installed")
    return True


def clean_artifacts():
    print_header("Cleaning old artifacts")
    removed = 0

    for name in ("build", "dist"):
        d = SCRIPT_DIR / name
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed {name}/")
            removed += 1

    for pat in ("Video2Shop_v*.exe", "*.spec"):
        for f in SCRIPT_DIR.glob(pat):
            f.unlink()
            print(f"  Removed {f.name}")
            removed += 1

    if removed == 0:
        print("  Nothing to clean")


def run_pyinstaller() -> bool:
    print_header("Running PyInstaller")
    print(f"  Entry: {ENTRY_POINT}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        f"--name={OUTPUT_NAME}",
    ]

    for src, dst in ADD_DATA:
        cmd.append(f"--add-data={src}{os.pathsep}{dst}")

    for imp in HIDDEN_IMPORTS:
        cmd.append(f"--hidden-import={imp}")

    for ca in COLLECT_ALL:
        cmd.append(f"--collect-all={ca}")

    for ex in EXCLUDE_MODULES:
        cmd.append(f"--exclude-module={ex}")

    cmd.append(ENTRY_POINT)

    print(f"  {Style.dim('─' * 58)}")

    r = subprocess.run(cmd, cwd=str(SCRIPT_DIR))

    if r.returncode != 0:
        print()
        print_err(f"PyInstaller exited with code {r.returncode}")
        return False

    print_ok("PyInstaller finished")
    return True


def verify_output() -> bool:
    print_header("Verifying output")
    if not EXE_SOURCE.exists():
        print_err(f"{EXE_SOURCE} was not generated")
        return False
    size = EXE_SOURCE.stat().st_size
    print_ok(f"dist/Video2Shop.exe  ({fmt_size(size)})")
    return True


def copy_to_root(version: str) -> bool:
    print_header("Copying to project root")
    dest_name = f"Video2Shop_v{version}.exe"
    dest = SCRIPT_DIR / dest_name
    try:
        shutil.copy2(EXE_SOURCE, dest)
        size = dest.stat().st_size
        print_ok(f"{dest_name}  ({fmt_size(size)})")
        return True
    except OSError as e:
        print_err(f"Copy failed: {e}")
        return False


def cleanup_work_files():
    print_header("Cleaning work files")
    build_dir = SCRIPT_DIR / "build"
    spec_files = list(SCRIPT_DIR.glob("*.spec"))

    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("  Removed build/")
    for f in spec_files:
        f.unlink()
        print(f"  Removed {f.name}")

    if not build_dir.exists() and not spec_files:
        print("  Nothing to clean")


def print_success(version: str):
    dest_name = f"Video2Shop_v{version}.exe"
    dest_path = SCRIPT_DIR / dest_name
    size = fmt_size(dest_path.stat().st_size) if dest_path.exists() else "?"

    print()
    print(Style.bold("=" * 60))
    print(Style.green(Style.bold("  BUILD SUCCESSFUL")))
    print(Style.bold("=" * 60))
    print()
    print(f"  Version:   {version}")
    print(f"  Output:    dist/Video2Shop.exe")
    print(f"  Root copy: {dest_name}  ({size})")
    print()
    print(f"  {Style.dim('Next: see RELEASE.md for publishing instructions')}")


def print_failure():
    print()
    print(Style.bold("=" * 60))
    print(Style.red(Style.bold("  BUILD FAILED")))
    print(Style.bold("=" * 60))
    print()
    print(f"  Check the messages above for details.")
    print(f"  Common fixes:")
    print(f"    1. pip install -r requirements.txt")
    print(f"    2. pip install --upgrade pyinstaller")
    print(f"    3. Make sure src/gui.py and config/ exist")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    # Ensure we're at the project root
    os.chdir(SCRIPT_DIR)

    print()
    print(Style.header("=" * 60))
    print(Style.header("  Video2Shop — Auto Build"))
    print(Style.header("=" * 60))

    clean_only = "--clean" in sys.argv
    keep_work = "--keep" in sys.argv

    # 1. Python version check
    if not check_python():
        print_failure()
        confirm_exit()
        sys.exit(1)

    # 2. Read version
    version = read_version()

    # --clean mode: just clean and exit
    if clean_only:
        clean_artifacts()
        print()
        print_ok("Clean complete.")
        confirm_exit()
        return

    # 3. PyInstaller
    if not ensure_pyinstaller():
        print_failure()
        confirm_exit()
        sys.exit(1)

    # 4. Clean
    clean_artifacts()

    # 5. Build
    if not run_pyinstaller():
        print_failure()
        confirm_exit()
        sys.exit(1)

    # 6. Verify
    if not verify_output():
        print_failure()
        confirm_exit()
        sys.exit(1)

    # 7. Copy to root
    copy_to_root(version)

    # 8. Clean work files (unless --keep)
    if not keep_work:
        cleanup_work_files()

    # Done
    print_success(version)
    confirm_exit()


if __name__ == "__main__":
    main()
