#!/usr/bin/env python3
"""
Video2Shop project reorganization script.

Run this script from the project root to:
  1. Create new directory structure (src/, config/, resources/templates/, scripts/)
  2. Update all path references in Python source files
  3. Move files to their new locations
  4. Update build.bat, .gitignore, and README.md

Usage:
    python reorganize.py          # Preview changes (dry-run)
    python reorganize.py --apply  # Apply all changes
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

NEW_DIRS = [
    ROOT / "src",
    ROOT / "config",
    ROOT / "resources" / "templates",
    ROOT / "scripts",
]

PY_FILES = [
    "pipeline.py",
    "video_processor.py",
    "deepseek_web_analyzer.py",
    "shopping_platform.py",
    "bili_downloader.py",
    "recipe_extractor.py",
    "web_interface.py",
    "web_app.py",
    "gui.py",
    "main.py",
]


def log(msg: str):
    print(f"  {msg}")


def step(header: str):
    print(f"\n{'=' * 60}")
    print(f"  {header}")
    print(f"{'=' * 60}")


# ─────────────────────────────────────────────────────────────────────────
#  Path replacement logic per-file
# ─────────────────────────────────────────────────────────────────────────


def patch_gui_py(content: str) -> str:
    """gui.py: PROJECT_DIR moves from parent to parent.parent, config paths updated."""
    # Add sys._MEIPASS support and adjust PROJECT_DIR
    old_project_dir = 'PROJECT_DIR = Path(__file__).resolve().parent'
    new_project_dir = (
        'if getattr(sys, "frozen", False):\n'
        '    PROJECT_DIR = Path(sys._MEIPASS)\n'
        'else:\n'
        '    PROJECT_DIR = Path(__file__).resolve().parent.parent'
    )
    content = content.replace(old_project_dir, new_project_dir)

    content = content.replace(
        'CONFIG_PATH = PROJECT_DIR / "config.yaml"',
        'CONFIG_PATH = PROJECT_DIR / "config" / "config.yaml"',
    )
    content = content.replace(
        'DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.default.yaml"',
        'DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "config.default.yaml"',
    )
    return content


def patch_web_app_py(content: str) -> str:
    """web_app.py: fix PROJECT_DIR, config paths, Flask template_folder.

    Must reorder so PROJECT_DIR is defined BEFORE app = Flask(...).
    """
    # Step 1: Remove the old PROJECT_DIR / CONFIG_PATH block (leaving a placeholder)
    old_block = (
        'PROJECT_DIR = Path(__file__).resolve().parent\n'
        'CONFIG_PATH = PROJECT_DIR / "config.yaml"\n'
        'DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.default.yaml"'
    )
    new_block = (
        'if getattr(sys, "frozen", False):\n'
        '    PROJECT_DIR = Path(sys._MEIPASS)\n'
        'else:\n'
        '    PROJECT_DIR = Path(__file__).resolve().parent.parent\n'
        'CONFIG_PATH = PROJECT_DIR / "config" / "config.yaml"\n'
        'DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "config.default.yaml"'
    )
    content = content.replace(old_block, new_block)

    # Step 2: Move the PROJECT_DIR block before "app = Flask(__name__)"
    old_section = (
        '# ── Flask 应用 ──'
    )

    # Find the Flask comment and ensure PROJECT_DIR block is right before it
    # Replace the original section heading + old_project_dir with reordered version
    if new_block in content and 'app = Flask(__name__)' in content:
        # Remove new_block from its original position (after Flask comment)
        # and place it before the Flask comment
        content = content.replace(
            old_section + '\n\n' + new_block,
            new_block + '\n\n# ── Flask 应用 ──'
        )
        # The above might not match if formatting differs. Handle common case:
        content = content.replace(
            '# ── Flask 应用 ──\n\n' + new_block,
            new_block + '\n\n# ── Flask 应用 ──'
        )

    # Step 3: Add template_folder to Flask()
    content = content.replace(
        'app = Flask(__name__)',
        'app = Flask(__name__, template_folder=str(PROJECT_DIR / "resources" / "templates"))'
    )

    return content


def patch_pipeline_py(content: str) -> str:
    """pipeline.py: default config path."""
    content = content.replace(
        'def load_config(config_path: str = "config.yaml")',
        'def load_config(config_path: str = "config/config.yaml")',
    )
    content = content.replace(
        'config_path: str = "config.yaml",',
        'config_path: str = "config/config.yaml",',
    )
    return content


def patch_main_py(content: str) -> str:
    """main.py: --config default."""
    content = content.replace(
        'default="config.yaml", help="配置文件路径"',
        'default="config/config.yaml", help="config file path"',
    )
    return content


def patch_deepseek_web_analyzer_py(content: str) -> str:
    """deepseek_web_analyzer.py: cookies_file default."""
    content = content.replace(
        '"deepseek_auth.json"',
        '"config/deepseek_auth.json"',
    )
    return content


def patch_shopping_platform_py(content: str) -> str:
    """shopping_platform.py: debug output paths."""
    content = content.replace(
        'path="debug_no_add_button.png"',
        'path="temp/debug_no_add_button.png"',
    )
    content = content.replace(
        'open("debug_page.html", "w"',
        'open("temp/debug_page.html", "w"',
    )
    return content


def patch_config_default_yaml(content: str) -> str:
    """config.default.yaml: update cookies_file path."""
    content = content.replace(
        'cookies_file: "deepseek_auth.json"',
        'cookies_file: "config/deepseek_auth.json"',
    )
    return content


# Files that don't need path changes
NO_PATCH = {"bili_downloader.py", "video_processor.py", "recipe_extractor.py", "web_interface.py"}

PATCHERS = {
    "gui.py": patch_gui_py,
    "web_app.py": patch_web_app_py,
    "pipeline.py": patch_pipeline_py,
    "main.py": patch_main_py,
    "deepseek_web_analyzer.py": patch_deepseek_web_analyzer_py,
    "shopping_platform.py": patch_shopping_platform_py,
}


# ─────────────────────────────────────────────────────────────────────────
#  Build script (.bat) update
# ─────────────────────────────────────────────────────────────────────────

NEW_BUILD_BAT = r"""@echo off
setlocal enabledelayedexpansion

REM Change to project root (this script lives in scripts/)
cd /d "%~dp0.."

echo ============================================================
echo   Video2Shop - PyInstaller Build Script (Single-file GUI)
echo ============================================================
echo.

REM Check if pyinstaller is installed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] pyinstaller not found, installing...
    pip install pyinstaller
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install pyinstaller. Please check your pip configuration.
        pause
        exit /b 1
    )
)

echo [1/3] Cleaning old build artifacts...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo [2/3] Building...

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

if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo   [ERROR] Build failed!
    echo ============================================================
    echo.
    echo   Please check the error messages above.
    echo   Common issues:
    echo     - Missing dependencies: run "pip install -r requirements.txt"
    echo     - Conflicting package versions: try upgrading pyinstaller
    echo     - File not found: ensure src\gui.py and config\config.default.yaml exist
    echo.
    pause
    exit /b 1
)

echo [3/3] Build completed!
echo.
echo Output file: dist\Video2Shop.exe
echo.
echo ── Usage Notes ──────────────────────────────────────────
echo 1. Copy dist\Video2Shop.exe to any folder and run it
echo 2. On first launch, config.yaml will be created automatically
echo 3. To restore default settings, delete config.yaml and restart
echo 4. Google Chrome is required for JD shopping cart feature
echo 5. First run may need: playwright install chromium
echo ─────────────────────────────────────────────────────────
echo.
pause
"""

# ─────────────────────────────────────────────────────────────────────────
#  .gitignore update
# ─────────────────────────────────────────────────────────────────────────

NEW_GITIGNORE = """# ── Python ──────────────────────────────────────────────────────────────
__pycache__/
*.py[cod]
*.pyo
*.egg-info/
dist/
build/
*.egg
.eggs/

# ── Virtual environments ────────────────────────────────────────────────
venv/
env/
.venv/
.env

# ── IDE / Editor ────────────────────────────────────────────────────────
.vscode/
.idea/
*.swp
*.swo
*~

# ── Project runtime files ───────────────────────────────────────────────
temp/
*.log
debug_no_add_button.png
debug_page.html
bili_video_*.json

# ── Sensitive config (contains secrets, DO NOT commit) ──────────────────
config/config.yaml
config/deepseek_auth.json

# ── Environment variables ───────────────────────────────────────────────
.env

# ── OS misc ─────────────────────────────────────────────────────────────
Thumbs.db
.DS_Store
Desktop.ini

# ── Test cache ──────────────────────────────────────────────────────────
.pytest_cache/
.coverage
htmlcov/

# ── PyInstaller ─────────────────────────────────────────────────────────
*.spec
"""


# ─────────────────────────────────────────────────────────────────────────
#  Main logic
# ─────────────────────────────────────────────────────────────────────────


def create_directories():
    for d in NEW_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        log(f"Created: {d.relative_to(ROOT)}")


def patch_python_files():
    for filename in PY_FILES:
        filepath = ROOT / filename
        if not filepath.exists():
            log(f"SKIP (not found): {filename}")
            continue

        original = filepath.read_text(encoding="utf-8")

        if filename in NO_PATCH:
            log(f"No changes needed: {filename}")
            continue

        patcher = PATCHERS.get(filename)
        if patcher:
            modified = patcher(original)
            if modified != original:
                filepath.write_text(modified, encoding="utf-8")
                log(f"Patched: {filename}")
            else:
                log(f"No changes applied: {filename}")


def move_python_files():
    for filename in PY_FILES:
        src = ROOT / filename
        dst = ROOT / "src" / filename
        if src.exists():
            shutil.move(str(src), str(dst))
            log(f"Moved: {filename} → src/{filename}")


def move_config_files():
    src_default = ROOT / "config.default.yaml"
    if src_default.exists():
        content = src_default.read_text(encoding="utf-8")
        content = patch_config_default_yaml(content)
        dst = ROOT / "config" / "config.default.yaml"
        dst.write_text(content, encoding="utf-8")
        src_default.unlink()
        log(f"Moved & patched: config.default.yaml → config/config.default.yaml")

    # Move config.yaml if it exists (runtime file)
    src_config = ROOT / "config.yaml"
    if src_config.exists():
        shutil.move(str(src_config), str(ROOT / "config" / "config.yaml"))
        log(f"Moved: config.yaml → config/config.yaml")

    # Move deepseek_auth.json if it exists
    src_auth = ROOT / "deepseek_auth.json"
    if src_auth.exists():
        shutil.move(str(src_auth), str(ROOT / "config" / "deepseek_auth.json"))
        log(f"Moved: deepseek_auth.json → config/deepseek_auth.json")


def move_template_files():
    src_templates = ROOT / "templates"
    if src_templates.is_dir():
        dst_templates = ROOT / "resources" / "templates"
        for f in src_templates.iterdir():
            shutil.move(str(f), str(dst_templates / f.name))
            log(f"Moved: templates/{f.name} → resources/templates/{f.name}")
        src_templates.rmdir()
        log(f"Removed: templates/")


def move_build_script():
    src_bat = ROOT / "build.bat"
    if src_bat.exists():
        dst = ROOT / "scripts" / "build.bat"
        dst.write_text(NEW_BUILD_BAT, encoding="utf-8")
        src_bat.unlink()
        log(f"Updated & moved: build.bat → scripts/build.bat")


def update_gitignore():
    gitignore = ROOT / ".gitignore"
    gitignore.write_text(NEW_GITIGNORE, encoding="utf-8")
    log("Updated: .gitignore")


def update_readme():
    readme_path = ROOT / "README.md"
    content = readme_path.read_text(encoding="utf-8")

    old_structure = """```
Video2Shop/
├── gui.py                     # 桌面 GUI 入口 (Tkinter + ttkbootstrap)
├── main.py                    # 命令行入口
├── web_app.py                 # Web 前端入口 (Flask)
├── pipeline.py                # 共享后端管道
├── video_processor.py         # 视频下载 + 抽帧 + OCR 筛选
├── deepseek_web_analyzer.py   # DeepSeek 网页版多图分析
├── recipe_extractor.py        # DeepSeek API 文本配方提取
├── shopping_platform.py       # 京东购物车自动化 (Playwright CDP)
├── web_interface.py           # Web 配方展示 + 加购界面
├── bili_downloader.py         # B站视频下载器
├── config.default.yaml        # 默认配置模板
├── config.yaml                # 运行时配置 (gitignore)
├── requirements.txt           # Python 依赖
├── requirements-gui.txt       # GUI 额外依赖
├── build.bat                  # PyInstaller 打包脚本
├── templates/                 # Web 前端 HTML 模板
├── packaging/                 # PyInstaller .spec 文件
└── tests/                     # 单元测试
```"""

    new_structure = """```
Video2Shop/
├── src/                           # Python source code
│   ├── gui.py                     # Desktop GUI entry (Tkinter + ttkbootstrap)
│   ├── main.py                    # CLI entry
│   ├── web_app.py                 # Web frontend entry (Flask)
│   ├── pipeline.py                # Shared backend pipeline
│   ├── video_processor.py         # Video download + frame extraction + OCR
│   ├── deepseek_web_analyzer.py   # DeepSeek web multi-image analysis
│   ├── recipe_extractor.py        # DeepSeek API text recipe extraction
│   ├── shopping_platform.py       # JD shopping cart automation (Playwright CDP)
│   ├── web_interface.py           # Web recipe display + cart interface
│   └── bili_downloader.py         # Bilibili video downloader
├── config/                        # Configuration files
│   ├── config.default.yaml        # Default config template
│   └── config.yaml                # Runtime config (gitignored)
├── resources/                     # Static resources
│   └── templates/                 # Web frontend HTML templates
├── scripts/                       # Helper scripts
│   └── build.bat                  # PyInstaller build script
├── temp/                          # Temporary files (gitignored)
├── tests/                         # Unit tests
├── requirements.txt               # Python dependencies
├── requirements-gui.txt           # GUI extra dependencies
├── .gitignore
└── README.md
```"""

    if old_structure in content:
        content = content.replace(old_structure, new_structure)
        log("Updated: README.md project structure")
    else:
        log("WARNING: Could not find old structure section in README.md")

    readme_path.write_text(content, encoding="utf-8")


def print_summary():
    print(f"""
{'=' * 60}
  Reorganization complete!
{'=' * 60}

New structure:
  src/          - All Python source files
  config/       - Configuration files (config.yaml, config.default.yaml)
  resources/    - Static resources (templates, icons, etc.)
  scripts/      - Helper scripts (build.bat)
  temp/         - Temporary files (gitignored)
  tests/        - Unit tests (unchanged)

Next steps:
  1. Run your tests to verify everything works:
       python -m pytest tests/ -v
  2. Update any external references to the old file paths
  3. The GUI entry point is now: python src/gui.py
  4. The CLI entry point is now: python src/main.py --url BV1xxx
  5. Build the exe: scripts\\build.bat
""")


def main():
    dry_run = "--apply" not in sys.argv

    if dry_run:
        print("=" * 60)
        print("  DRY RUN — no changes will be made")
        print("  Run with --apply to execute the reorganization")
        print("=" * 60)
        print()
        print("Would create directories:")
        for d in NEW_DIRS:
            print(f"  {d.relative_to(ROOT)}/")
        print()
        print("Would patch Python files:")
        for f in PY_FILES:
            if f not in NO_PATCH:
                print(f"  {f}")
        print()
        print("Would move files:")
        print(f"  *.py → src/")
        print(f"  config.default.yaml → config/")
        print(f"  config.yaml → config/")
        print(f"  deepseek_auth.json → config/")
        print(f"  templates/ → resources/templates/")
        print(f"  build.bat → scripts/")
        print()
        print("Would update:")
        print(f"  .gitignore")
        print(f"  README.md")
        print()
        print("Run with --apply to execute.")
        return

    # ── Apply mode ──────────────────────────────────────────────────────
    step("1/6  Creating directories")
    create_directories()

    step("2/6  Patching Python file paths")
    patch_python_files()

    step("3/6  Moving Python files → src/")
    move_python_files()

    step("4/6  Moving config & template files")
    move_config_files()
    move_template_files()

    step("5/6  Updating build script, .gitignore, README")
    move_build_script()
    update_gitignore()
    update_readme()

    step("6/6  Done")
    print_summary()


if __name__ == "__main__":
    main()
