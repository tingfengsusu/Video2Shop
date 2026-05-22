#!/usr/bin/env python3
"""
Video2Shop — One-Click Auto Build Script
=========================================
Double-click to build Video2Shop with zero manual steps.

What it does:
  1. Reads version from src/version.py
  2. Checks / installs PyInstaller
  3. Auto-downloads UPX for compression
  4. Cleans old build artifacts
  5. Runs PyInstaller (--onedir, no bundled EasyOCR models)
  6. Verifies dist/Video2Shop/Video2Shop.exe
  7. Zips the onedir folder for distribution
  8. Prints a friendly success / failure summary

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
import zipfile
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).resolve().parent
VERSION_FILE = SCRIPT_DIR / "src" / "version.py"
DIST_DIR     = SCRIPT_DIR / "dist" / "Video2Shop"
EXE_SOURCE   = DIST_DIR / "Video2Shop.exe"

# PyInstaller parameters — keep in sync with scripts/build.bat
ENTRY_POINT      = "src" + os.sep + "gui.py"
OUTPUT_NAME      = "Video2Shop"

HIDDEN_IMPORTS = [
    "yaml", "PIL", "PIL.Image", "cv2", "numpy", "easyocr",
    "playwright", "playwright.sync_api", "requests",
    "pipeline", "video_processor", "deepseek_web_analyzer",
    "shopping_platform", "web_interface", "recipe_extractor",
    "bili_downloader", "ttkbootstrap", "version",
]

# Only collect-all for ttkbootstrap (themes are small).
# easyocr models (~200MB) are NOT bundled — they auto-download to ~/.EasyOCR on first run.
COLLECT_ALL = ["ttkbootstrap"]

EXCLUDE_MODULES = [
    "flask", "jinja2", "werkzeug", "markupsafe",
    "itsdangerous", "blinker", "click",
]

# --add-data pairs: (source, dest)
ADD_DATA = [
    ("config" + os.sep + "config.default.yaml", "config"),
    ("resources" + os.sep + "templates", "resources" + os.sep + "templates"),
    ("tools" + os.sep + "ffmpeg.exe", "tools"),
]

MIN_PYTHON = (3, 8)
UPX_VERSION = "4.2.4"
UPX_URL = f"https://github.com/upx/upx/releases/download/v{UPX_VERSION}/upx-{UPX_VERSION}-win64.zip"


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

    _ON = _enable.__func__()

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
    print()
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


def fmt_size(bytes_: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"


def dir_size(path: Path) -> int:
    """Total size of all files in a directory tree."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# ── UPX ────────────────────────────────────────────────────────────────────

def find_upx() -> Path | None:
    """Look for upx.exe on PATH or in tools/."""
    which = shutil.which("upx")
    if which:
        return Path(which)
    local = SCRIPT_DIR / "tools" / "upx.exe"
    if local.exists():
        return local
    return None


def ensure_upx() -> Path | None:
    """Ensure UPX is available. Download to tools/ if missing."""
    print_header("Checking UPX")

    existing = find_upx()
    if existing:
        print_ok(f"UPX found: {existing}")
        return existing

    print_info("UPX not found, downloading...")
    tools_dir = SCRIPT_DIR / "tools"
    tools_dir.mkdir(exist_ok=True)

    zip_path = tools_dir / "upx.zip"
    upx_exe = tools_dir / "upx.exe"

    try:
        import urllib.request
        print_info(f"Downloading {UPX_URL}")
        urllib.request.urlretrieve(UPX_URL, zip_path)

        import zipfile
        with zipfile.ZipFile(zip_path, "r") as zf:
            # UPX zip contains: upx-4.2.4-win64/upx.exe
            for name in zf.namelist():
                if name.endswith("upx.exe"):
                    with zf.open(name) as src, open(upx_exe, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break

        zip_path.unlink()  # clean up zip
        print_ok(f"UPX installed to {upx_exe}")
        return upx_exe

    except Exception as e:
        print_warn(f"UPX download failed ({e}), building without compression")
        if zip_path.exists():
            zip_path.unlink()
        return None


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

    for pat in ("Video2Shop_v*.zip", "Video2Shop_v*.exe", "*.spec"):
        for f in SCRIPT_DIR.glob(pat):
            f.unlink()
            print(f"  Removed {f.name}")
            removed += 1

    if removed == 0:
        print("  Nothing to clean")


def run_pyinstaller(upx_path: Path | None) -> bool:
    print_header("Running PyInstaller")
    print(f"  Entry: {ENTRY_POINT}")
    print(f"  Mode:  --onedir")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconsole",
        f"--name={OUTPUT_NAME}",
    ]

    if upx_path:
        cmd.append(f"--upx-dir={upx_path.parent}")

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
    size = dir_size(DIST_DIR)
    print_ok(f"dist/Video2Shop/  ({fmt_size(size)})")
    return True


def zip_dist(version: str) -> bool:
    print_header("Creating distribution zip")
    dest_name = f"Video2Shop_v{version}.zip"
    dest = SCRIPT_DIR / dest_name

    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in DIST_DIR.rglob("*"):
                if file.is_file():
                    arcname = f"Video2Shop/{file.relative_to(DIST_DIR)}"
                    zf.write(file, arcname)
        size = dest.stat().st_size
        print_ok(f"{dest_name}  ({fmt_size(size)})")
        return True
    except OSError as e:
        print_err(f"Zip failed: {e}")
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
    dest_name = f"Video2Shop_v{version}.zip"
    dest_path = SCRIPT_DIR / dest_name
    size = fmt_size(dest_path.stat().st_size) if dest_path.exists() else "?"

    print()
    print(Style.bold("=" * 60))
    print(Style.green(Style.bold("  BUILD SUCCESSFUL")))
    print(Style.bold("=" * 60))
    print()
    print(f"  Version:   {version}")
    print(f"  Output:    dist/Video2Shop/")
    print(f"  Zip:       {dest_name}  ({size})")
    print()
    print(f"  {Style.dim('EasyOCR models will download on first run (~100MB).')}")
    print(f"  {Style.dim('For installer build, see: scripts/setup.iss')}")


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
    os.chdir(SCRIPT_DIR)

    print()
    print(Style.header("=" * 60))
    print(Style.header("  Video2Shop — Auto Build"))
    print(Style.header("=" * 60))

    clean_only = "--clean" in sys.argv
    keep_work = "--keep" in sys.argv

    if not check_python():
        print_failure()
        confirm_exit()
        sys.exit(1)

    version = read_version()

    if clean_only:
        clean_artifacts()
        print()
        print_ok("Clean complete.")
        confirm_exit()
        return

    if not ensure_pyinstaller():
        print_failure()
        confirm_exit()
        sys.exit(1)

    upx_path = ensure_upx()

    clean_artifacts()

    if not run_pyinstaller(upx_path):
        print_failure()
        confirm_exit()
        sys.exit(1)

    if not verify_output():
        print_failure()
        confirm_exit()
        sys.exit(1)

    zip_dist(version)

    if not keep_work:
        cleanup_work_files()

    print_success(version)
    confirm_exit()


if __name__ == "__main__":
    main()
