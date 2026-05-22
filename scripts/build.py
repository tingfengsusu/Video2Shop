#!/usr/bin/env python3
"""
Video2Shop — PyInstaller Build Script (cross-platform).

Usage:
    python scripts/build.py              # use version from src/version.py
    python scripts/build.py --version 1.0.1
    python scripts/build.py --clean      # clean only, no build
    python scripts/build.py --dry-run    # print command without running

Works on Windows, Linux, and macOS.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR      = PROJECT_ROOT / "src"
VERSION_FILE = SRC_DIR / "version.py"
DIST_DIR     = PROJECT_ROOT / "dist" / "Video2Shop"
EXE_SOURCE   = DIST_DIR / "Video2Shop.exe"

CONFIG_SRC   = "config" + os.sep + "config.default.yaml"
CONFIG_DST   = "config"
TEMPLATES_SRC = "resources" + os.sep + "templates"
TEMPLATES_DST = "resources" + os.sep + "templates"
FFMPEG_SRC = "tools" + os.sep + "ffmpeg.exe"
FFMPEG_DST = "tools"
ENTRY_POINT  = "src" + os.sep + "gui.py"

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


# ── helpers ─────────────────────────────────────────────────────────────

def read_version() -> str:
    """Extract __version__ from src/version.py."""
    if not VERSION_FILE.exists():
        return "1.0.0"
    content = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else "1.0.0"


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a command with console output forwarded."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=str(PROJECT_ROOT), **kwargs)


def check_pyinstaller() -> bool:
    """Return True if pyinstaller is importable."""
    try:
        import PyInstaller
        return True
    except ImportError:
        return False


def find_upx() -> Path | None:
    """Look for upx on PATH or in tools/."""
    which = shutil.which("upx")
    if which:
        return Path(which).parent
    local = PROJECT_ROOT / "tools" / "upx.exe"
    if local.exists():
        return local.parent
    return None


def clean():
    """Remove build artifacts."""
    print("[clean] Removing build artifacts...")
    for name in ["build", "dist"]:
        d = PROJECT_ROOT / name
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed {name}/")
    for pat in ["Video2Shop_v*.zip", "Video2Shop_v*.exe", "Video2Shop.spec"]:
        for f in PROJECT_ROOT.glob(pat):
            f.unlink()
            print(f"  Removed {f.name}")


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# ── build ───────────────────────────────────────────────────────────────

def build(version: str, dry_run: bool = False):
    """Run the full PyInstaller build pipeline."""
    print(f"Video2Shop — PyInstaller Build  (version: {version})")
    print(f"Project root: {PROJECT_ROOT}")
    print()

    # 1. install pyinstaller if missing
    if not check_pyinstaller():
        print("[1/6] Installing pyinstaller...")
        r = run([sys.executable, "-m", "pip", "install", "pyinstaller"])
        if r.returncode != 0:
            print("[ERROR] Failed to install pyinstaller.")
            sys.exit(1)
    else:
        print("[1/6] pyinstaller already installed.")

    # 2. check UPX
    upx_dir = find_upx()
    if upx_dir:
        print(f"[2/6] UPX found: {upx_dir}")
    else:
        print("[2/6] UPX not found — building without compression.")

    # 3. clean
    clean()

    # 4. build command
    print("\n[3/6] Running PyInstaller (--onedir)...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconsole",
        "--name=Video2Shop",
        f"--add-data={CONFIG_SRC}{os.pathsep}{CONFIG_DST}",
        f"--add-data={TEMPLATES_SRC}{os.pathsep}{TEMPLATES_DST}",
        f"--add-data={FFMPEG_SRC}{os.pathsep}{FFMPEG_DST}",
    ]

    if upx_dir:
        cmd.append(f"--upx-dir={upx_dir}")

    for imp in HIDDEN_IMPORTS:
        cmd.append(f"--hidden-import={imp}")
    for ca in COLLECT_ALL:
        cmd.append(f"--collect-all={ca}")
    for ex in EXCLUDE_MODULES:
        cmd.append(f"--exclude-module={ex}")

    cmd.append(ENTRY_POINT)

    if dry_run:
        print("  [DRY-RUN] Would execute:")
        print(f"  {' '.join(cmd)}")
        return

    r = run(cmd)
    if r.returncode != 0:
        print("\n[ERROR] PyInstaller build failed!")
        print("  Common issues:")
        print("    - Missing deps: pip install -r requirements.txt")
        print("    - Conflicting packages: pip install --upgrade pyinstaller")
        sys.exit(1)

    # 5. verify
    print("\n[4/6] Verifying output...")
    if not EXE_SOURCE.exists():
        print(f"[ERROR] {EXE_SOURCE} was not generated.")
        sys.exit(1)
    size = dir_size(DIST_DIR)
    print(f"  OK: dist/Video2Shop/  ({size / (1024*1024):.1f} MB)")

    # 6. zip for distribution
    print(f"\n[5/6] Creating distribution zip...")
    zip_name = f"Video2Shop_v{version}.zip"
    zip_path = PROJECT_ROOT / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in DIST_DIR.rglob("*"):
            if file.is_file():
                arcname = f"Video2Shop/{file.relative_to(DIST_DIR)}"
                zf.write(file, arcname)
    zip_size = zip_path.stat().st_size / (1024 * 1024)
    print(f"  Created: {zip_name} ({zip_size:.1f} MB)")

    # 7. clean work files
    print("\n[6/6] Cleaning PyInstaller work files...")
    build_dir = PROJECT_ROOT / "build"
    spec_file = PROJECT_ROOT / "Video2Shop.spec"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if spec_file.exists():
        spec_file.unlink()
    print("  Done.")

    # done
    print(f"""
{'=' * 60}
  Build complete!
{'=' * 60}

  Version:  {version}
  Output:   dist/Video2Shop/
  Zip:      {zip_name}  ({zip_size:.1f} MB)

  Note: EasyOCR models (~100MB) will download on first run.
  For installer build, see: scripts/setup.iss
""")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Video2Shop build script")
    parser.add_argument("--version", "-v", default=None,
                        help="Version override (default: read from src/version.py)")
    parser.add_argument("--clean", action="store_true",
                        help="Only clean build artifacts, don't build")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the pyinstaller command without running it")
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    version = args.version or read_version()
    build(version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
