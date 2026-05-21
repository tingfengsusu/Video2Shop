#!/usr/bin/env python3
"""
Bump Video2Shop version in src/version.py.

Usage:
    python scripts/version_bump.py patch    # 1.0.0 → 1.0.1
    python scripts/version_bump.py minor    # 1.0.1 → 1.1.0
    python scripts/version_bump.py major    # 1.1.0 → 2.0.0
    python scripts/version_bump.py 2.0.0    # set exact version
    python scripts/version_bump.py          # show current version
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "src" / "version.py"


def read_version() -> str:
    content = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else "0.0.0"


def write_version(version: str):
    VERSION_FILE.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    print(f"Version: {version}  (written to src/version.py)")


def bump(component: str):
    major, minor, patch = map(int, read_version().split("."))
    if component == "major":
        major += 1
    elif component == "minor":
        minor += 1
    elif component == "patch":
        patch += 1
    else:
        print(f"Usage: python {Path(__file__).name} [major|minor|patch|<version>]")
        sys.exit(1)
    write_version(f"{major}.{minor}.{patch}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Current version: {read_version()}")
        print(f"Usage: python {Path(__file__).name} [major|minor|patch|<version>]")
    elif sys.argv[1] in ("major", "minor", "patch"):
        bump(sys.argv[1])
    else:
        write_version(sys.argv[1])
