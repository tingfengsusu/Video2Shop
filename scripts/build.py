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
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR      = PROJECT_ROOT / "src"
VERSION_FILE = SRC_DIR / "version.py"
CONFIG_SRC   = "config" + os.sep + "config.default.yaml"
CONFIG_DST   = "config"
TEMPLATES_SRC = "resources" + os.sep + "templates"
TEMPLATES_DST = "resources" + os.sep + "templates"
ENTRY_POINT  = "src" + os.sep + "gui.py"

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


def clean():
    """Remove build artifacts."""
    print("[clean] Removing build artifacts...")
    for name in ["build", "dist"]:
        d = PROJECT_ROOT / name
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed {name}/")
    for pat in ["Video2Shop_v*.exe", "Video2Shop.spec"]:
        for f in PROJECT_ROOT.glob(pat):
            f.unlink()
            print(f"  Removed {f.name}")


# ── build ───────────────────────────────────────────────────────────────

def build(version: str, dry_run: bool = False):
    """Run the full PyInstaller build pipeline."""
    print(f"Video2Shop — PyInstaller Build  (version: {version})")
    print(f"Project root: {PROJECT_ROOT}")
    print()

    # 1. install pyinstaller if missing
    if not check_pyinstaller():
        print("[1/5] Installing pyinstaller...")
        r = run([sys.executable, "-m", "pip", "install", "pyinstaller"])
        if r.returncode != 0:
            print("[ERROR] Failed to install pyinstaller.")
            sys.exit(1)
    else:
        print("[1/5] pyinstaller already installed.")

    # 2. clean
    clean()

    # 3. build command
    print("\n[2/5] Running PyInstaller...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name=Video2Shop",
        f"--add-data={CONFIG_SRC}{os.pathsep}{CONFIG_DST}",
        f"--add-data={TEMPLATES_SRC}{os.pathsep}{TEMPLATES_DST}",
    ]

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

    # 4. verify
    print("\n[3/5] Verifying output...")
    exe = PROJECT_ROOT / "dist" / "Video2Shop.exe"
    if not exe.exists():
        print(f"[ERROR] {exe} was not generated.")
        sys.exit(1)
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"  OK: dist/Video2Shop.exe ({size_mb:.1f} MB)")

    # 5. copy to root
    print(f"\n[4/5] Copying EXE to project root...")
    output_name = f"Video2Shop_v{version}.exe"
    dest = PROJECT_ROOT / output_name
    shutil.copy2(exe, dest)
    print(f"  Copied: {output_name}")

    # 6. clean work files
    print("\n[5/5] Cleaning PyInstaller work files...")
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
  Output:   dist/Video2Shop.exe
  Copy:     {output_name}

  Next steps:
    1. Test the EXE:  .\\{output_name}
    2. Follow RELEASE.md to publish to GitHub
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
