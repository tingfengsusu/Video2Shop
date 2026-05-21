# Video2Shop — Release Guide

How to build, test, and publish Video2Shop.

---

## 1. Build the EXE

### Option A: Windows batch script

```batch
cd scripts
build.bat
```

You can override the version:

```batch
build.bat 1.0.1
```

### Option B: Python script (cross-platform)

```bash
python scripts/build.py
python scripts/build.py --version 1.0.1
python scripts/build.py --dry-run    # preview without building
```

### What the build does

1. Reads version from `src/version.py` (or command-line override)
2. Cleans old `dist/`, `build/`, and root `Video2Shop_v*.exe`
3. Runs PyInstaller with `--onefile --noconsole`
4. Verifies output `dist/Video2Shop.exe`
5. Copies to project root as `Video2Shop_v<version>.exe`
6. Cleans PyInstaller work files (`build/`, `*.spec`)

---

## 2. Bump the Version

Before a new release, bump the version:

```bash
python scripts/version_bump.py patch   # 1.0.0 → 1.0.1
python scripts/version_bump.py minor   # 1.0.1 → 1.1.0
python scripts/version_bump.py major   # 1.1.0 → 2.0.0
python scripts/version_bump.py 2.0.0   # set exact version
```

This edits `src/version.py`. Rebuild after bumping.

---

## 3. Test the EXE

Test in a clean environment where Python is NOT installed:

```batch
REM Copy to a clean folder
mkdir C:\temp\v2s-test
copy Video2Shop_v1.0.0.exe C:\temp\v2s-test\
cd C:\temp\v2s-test

REM Run it
Video2Shop_v1.0.0.exe
```

Checklist:

- [ ] GUI launches without DLL errors
- [ ] `config/config.yaml` is auto-created on first run (no crash)
- [ ] Settings dialog opens and saves correctly
- [ ] Video URL input works (test with a short Bilibili video)
- [ ] No missing import errors in the console (run without `--noconsole` for testing)
- [ ] `config.default.yaml` can be read (defaults load correctly)
- [ ] `resources/templates/` files are accessible (if using Web mode)

Debug tip: temporarily remove `--noconsole` from the build script to see error output:

```batch
REM In build.bat, temporarily replace:
REM   --noconsole ^
REM with:
REM   --console ^
```

---

## 4. Create a GitHub Release

### Prerequisites

Install and authenticate GitHub CLI:

```batch
winget install GitHub.cli
gh auth login
```

### Create the release

```batch
gh release create v1.0.0 Video2Shop_v1.0.0.exe ^
    --title "Video2Shop v1.0.0" ^
    --notes "Release notes here"
```

Or use the auto-deploy script at the project root:

```batch
auto_deploy.bat
```

This automates: build → release → push.

### Release notes template

```markdown
## What's New

- Feature A
- Fix B

## Installation

1. Download `Video2Shop_v1.0.0.exe`
2. Ensure Google Chrome is installed
3. Double-click to run

## Requirements

- Windows 10/11
- Google Chrome (for JD shopping cart)
- Optional: `playwright install chromium` (for DeepSeek web mode)
```

---

## 5. Project File Layout (Packaging Reference)

```
Video2Shop/
├── src/
│   ├── gui.py                  ← entry point for EXE
│   ├── version.py              ← version number
│   └── ...                     ← other modules
├── config/
│   └── config.default.yaml     ← bundled into EXE
├── resources/
│   └── templates/              ← bundled into EXE
├── scripts/
│   ├── build.bat               ← Windows build
│   ├── build.py                ← cross-platform build
│   └── version_bump.py         ← version helper
├── dist/
│   └── Video2Shop.exe          ← build output (gitignored)
├── Video2Shop_v1.0.0.exe       ← root copy (gitignored)
└── RELEASE.md                  ← this file
```

### How paths work at runtime

The entry point `src/gui.py` resolves paths like this:

```python
if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys._MEIPASS)          # PyInstaller temp dir
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent  # project root
```

So `PROJECT_DIR / "config" / "config.yaml"` works in both dev and frozen modes.
