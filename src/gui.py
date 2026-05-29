"""
Video2Shop 桌面 GUI — 现代卡片式界面 (ttkbootstrap)

布局:
  ┌──────────────────────────────────────────────────────────┐
  │  ▎Video2Shop                              v1.0           │
  ├────────────┬─────────────────────────────────────────────┤
  │  侧边栏    │  主区域 (Notebook 标签页)                   │
  │            │  ┌─ 📋 配方清单 ─┬─ 📝 执行日志 ─┐        │
  │  URL 输入  │  │ 食材 (卡片)   │ 日志输出        │        │
  │  ┌──────┐  │  │ ☑ 面粉 100g  │                 │        │
  │  │      │  │  │ ☑ 糖 50g     │                 │        │
  │  └──────┘  │  ├──────────────┤                 │        │
  │  [▶ 启动] │  │ 工具 (卡片)   │                 │        │
  │  [■ 停止] │  │ ☑ 打蛋器      │                 │        │
  │  [⚙ 设置] │  │ ☑ 模具        │                 │        │
  │  ──────── │  └──────────────┴─────────────────┘        │
  │  进度条   │  [🛒 加购 3 件] [↺ 重置]                    │
  ├────────────┴─────────────────────────────────────────────┤
  │  ● 就绪                          已拥有 5/8 | 待加购 3  │
  └──────────────────────────────────────────────────────────┘

启动: python gui.py
依赖: pip install ttkbootstrap pyyaml
"""

import logging
import os
import re
import shutil
import sys

from version import __version__
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

import yaml

from preflight import PreflightCheck, CheckStatus

# ── ttkbootstrap 检测 ─────────────────────────────────────────────────────

try:
    import ttkbootstrap as ttkb
    from ttkbootstrap.constants import *
    from ttkbootstrap.scrolled import ScrolledText as BtScrolledText
    from ttkbootstrap.dialogs import Messagebox

    HAS_TTKB = True
except ImportError:
    HAS_TTKB = False
    ttkb = None
    print("💡 提示: pip install ttkbootstrap 可获得更佳视觉效果")

# ── 常量 ──────────────────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    # Frozen (exe) mode:
    #   RESOURCES_DIR  = PyInstaller temp dir (read-only, holds bundled assets)
    #   WRITABLE_DIR   = directory next to the exe (writable, holds config.yaml)
    RESOURCES_DIR = Path(sys._MEIPASS)
    WRITABLE_DIR  = Path(sys.executable).resolve().parent
else:
    # Dev mode: everything relative to the project root
    RESOURCES_DIR = Path(__file__).resolve().parent.parent
    WRITABLE_DIR  = RESOURCES_DIR

CONFIG_PATH = WRITABLE_DIR / "config" / "config.yaml"
DEFAULT_CONFIG_PATH = RESOURCES_DIR / "config" / "config.default.yaml"

SECTION_LABELS = {
    "deepseek": "DeepSeek API",
    "deepseek_web": "DeepSeek 网页版",
    "ocr": "OCR 设置",
    "shopping": "京东加购",
    "video": "视频处理",
    "gui": "通用",
}

SETTINGS_FIELDS = [
    ("deepseek.analysis_mode", "配方提取方式", "choice",
     {"choices": ["api", "web"]}),
    ("deepseek.api_key", "API Key", "str", {}),
    ("deepseek_web.timeout_seconds", "回复超时(秒)", "int",
     {"from": 30, "to": 600}),
    ("deepseek_web.batch_size", "每批图片数", "int",
     {"from": 1, "to": 10}),
    ("deepseek_web.headless", "无头模式", "bool", {}),
    ("ocr.min_chinese_chars", "最少中文字符数", "int",
     {"from": 5, "to": 100}),
    ("ocr.easyocr_device", "OCR 设备", "choice",
     {"choices": ["cpu", "cuda"]}),
    ("shopping.chrome_browser_type", "浏览器类型", "choice",
     {"choices": ["Google Chrome", "Microsoft Edge", "Chromium", "自定义路径"]}),
    ("shopping.add_cart_delay", "加购后延迟(秒)", "float",
     {"from": 0.1, "to": 5, "step": 0.1}),
    ("shopping.search_wait_after", "搜索后等待(秒)", "float",
     {"from": 0, "to": 5, "step": 0.1}),
    ("shopping.click_retry", "点击重试次数", "int",
     {"from": 0, "to": 5}),
    ("shopping.retry_on_failure", "失败时刷新重试", "bool", {}),
    ("video.frame_interval", "抽帧间隔(秒)", "int",
     {"from": 1, "to": 30}),
    ("video.max_frames", "最大抽帧数", "int",
     {"from": 3, "to": 50}),
    ("gui.startup_check", "启动时自动检查", "bool", {}),
]

# ── 工具函数 ──────────────────────────────────────────────────────────────


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        # Auto-init: copy default template if config doesn't exist yet
        if DEFAULT_CONFIG_PATH.exists():
            _reset_config()
        else:
            return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_config(data: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)
        f.flush()
        os.fsync(f.fileno())


def _reset_config():
    if not DEFAULT_CONFIG_PATH.exists():
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(DEFAULT_CONFIG_PATH, CONFIG_PATH)


def _get_nested(d: dict, keys: list):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d


def _set_nested(d: dict, keys: list, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


# ── 可滚动复选框面板 ──────────────────────────────────────────────────────


class ScrollableCheckPanel(ttk.LabelFrame):
    """带垂直滚动条的复选框列表面板（卡片式）。"""

    def __init__(self, parent, title: str, **kw):
        super().__init__(parent, text=title, padding=8, **kw)
        self._check_vars: list = []  # [(name, tk.BooleanVar)]

        # 工具栏 — 全选/全不选 + 计数
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))

        self._btn_all = ttk.Button(
            toolbar, text="全选", command=lambda: self._toggle_all(True))
        self._btn_all.pack(side="left", padx=2)

        self._btn_none = ttk.Button(
            toolbar, text="全不选", command=lambda: self._toggle_all(False))
        self._btn_none.pack(side="left", padx=2)

        self._count_var = tk.StringVar(value="0 项")
        ttk.Label(toolbar, textvariable=self._count_var,
                  foreground="gray").pack(side="right", padx=4)

        # Canvas + Scrollbar
        self._canvas = tk.Canvas(self, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)

        self._inner_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw", tags="inner")

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        for w in (self._canvas, self._inner):
            w.bind("<MouseWheel>", self._on_mousewheel)

    def _on_inner_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig("inner", width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _toggle_all(self, checked: bool):
        for _, var in self._check_vars:
            var.set(checked)

    def clear(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._count_var.set("0 项")

    def populate(self, items: list, is_ingredient: bool = True):
        self.clear()
        for item in items:
            if is_ingredient:
                name = item.get("name", "")
                amount = item.get("amount", "适量")
                label = (f"{name}  ({amount})"
                         if amount and amount != "适量" else name)
            else:
                name = item if isinstance(item, str) else str(item)
                label = name

            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self._inner, text=label, variable=var)
            cb.pack(anchor="w", padx=8, pady=2)
            self._check_vars.append((name, var))
        self._count_var.set(f"{len(self._check_vars)} 项")

    @property
    def checked_items(self) -> list:
        return [name for name, var in self._check_vars if var.get()]

    @property
    def unchecked_items(self) -> list:
        return [name for name, var in self._check_vars if not var.get()]

    @property
    def total(self) -> int:
        return len(self._check_vars)

    @property
    def checked_count(self) -> int:
        return sum(1 for _, var in self._check_vars if var.get())


# ── 设置对话框 ────────────────────────────────────────────────────────────


class SettingsDialog(tk.Toplevel):
    """卡片式设置对话框（模态）。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("设置")
        self.minsize(480, 400)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        # 居中于父窗口
        w, h = 540, 620
        px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        # 边界保护
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if px < 0:
            px = 0
        if py < 0:
            py = 0
        if px + w > sw:
            px = sw - w
        if py + h > sh:
            py = sh - h
        self.geometry(f"{w}x{h}+{px}+{py}")

        # 可滚动的画布
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self._form = ttk.Frame(canvas)

        self._form.bind("<Configure>",
                        lambda e: canvas.configure(
                            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        scrollbar.pack(side="right", fill="y", pady=8)

        def _mw(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        for w in (canvas, self._form):
            w.bind("<MouseWheel>", _mw)

        self._widgets = {}
        self._build_form()
        self._load_config()

        # 底部按钮 — 垂直排列
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=16, pady=(4, 12))
        ttk.Button(btn_frame, text="↺ 恢复默认",
                   command=self._on_reset).pack(
            fill="x", pady=(0, 6))
        if HAS_TTKB:
            ttk.Button(btn_frame, text="保存", bootstyle="primary",
                       command=self._on_save).pack(fill="x")
        else:
            ttk.Button(btn_frame, text="保存",
                       command=self._on_save).pack(fill="x")

    # ── 表单构建 ──────────────────────────────────────────────────────

    def _build_form(self):
        sections = {}
        for key, label, ftype, extra in SETTINGS_FIELDS:
            sec = key.split(".")[0]
            sections.setdefault(sec, []).append((key, label, ftype, extra))

        row = 0
        for sec, fields in sections.items():
            # 区域标题
            ttk.Label(self._form, text=SECTION_LABELS.get(sec, sec),
                      font=("", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w",
                padx=8, pady=(12, 4))
            row += 1

            # 分隔线
            sep = ttk.Separator(self._form, orient="horizontal")
            sep.grid(row=row, column=0, columnspan=2, sticky="ew",
                     padx=8, pady=(0, 6))
            row += 1

            for key, label, ftype, extra in fields:
                ttk.Label(self._form, text=label, anchor="e").grid(
                    row=row, column=0, sticky="e", padx=(20, 8), pady=4)

                if ftype == "bool":
                    var = tk.BooleanVar()
                    ttk.Checkbutton(self._form, variable=var).grid(
                        row=row, column=1, sticky="w", pady=4)
                    self._widgets[key] = ("bool", var)
                elif ftype == "choice":
                    var = tk.StringVar()
                    ttk.Combobox(
                        self._form, textvariable=var,
                        values=extra["choices"],
                        state="readonly", width=20
                    ).grid(row=row, column=1, sticky="w", pady=4)
                    self._widgets[key] = ("str", var)
                elif ftype in ("int", "float"):
                    var = tk.StringVar()
                    ttk.Spinbox(
                        self._form, textvariable=var,
                        from_=extra.get("from", 0),
                        to=extra.get("to", 100),
                        increment=extra.get("step", 1),
                        width=22
                    ).grid(row=row, column=1, sticky="w", pady=4)
                    self._widgets[key] = (ftype, var)
                else:  # str
                    var = tk.StringVar()
                    is_key = "key" in label.lower()
                    entry_kw = {"textvariable": var, "width": 28}
                    if is_key:
                        entry_kw["show"] = "*"
                    ttk.Entry(self._form, **entry_kw).grid(
                        row=row, column=1, sticky="w", pady=4)
                    self._widgets[key] = ("str", var)
                row += 1

            # 浏览器自定义路径（仅 shopping 区域后追加）
            if sec == "shopping":
                ttk.Label(self._form, text="浏览器路径",
                          anchor="e").grid(
                    row=row, column=0, sticky="e", padx=(20, 8), pady=4)

                pf = ttk.Frame(self._form)
                pf.grid(row=row, column=1, sticky="w", pady=4)

                self._chrome_path_var = tk.StringVar()
                self._chrome_path_entry = ttk.Entry(
                    pf, textvariable=self._chrome_path_var, width=20)
                self._chrome_path_entry.pack(side="left")

                browse_btn = ttk.Button(
                    pf, text="浏览...",
                    command=self._browse_browser_path, width=6)
                browse_btn.pack(side="left", padx=(4, 0))

                self._chrome_path_label = (
                    self._form.grid_slaves(row=row, column=0)[0])
                self._chrome_path_ctrls = (
                    self._chrome_path_entry, browse_btn)
                row += 1

                # 监听浏览器类型下拉框
                bt_widget = self._widgets.get(
                    "shopping.chrome_browser_type")
                if bt_widget:
                    _, btv = bt_widget
                    btv.trace_add("write", self._on_browser_type_changed)

    def _browse_browser_path(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择浏览器可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if path:
            self._chrome_path_var.set(path)

    def _on_browser_type_changed(self, *args):
        bt_widget = self._widgets.get("shopping.chrome_browser_type")
        if not bt_widget:
            return
        _, btv = bt_widget
        is_custom = btv.get() == "自定义路径"
        state = "normal" if is_custom else "disabled"
        self._chrome_path_label.configure(state=state)
        for w in self._chrome_path_ctrls:
            w.configure(state=state)
        if not is_custom:
            self._chrome_path_var.set("")

    # ── 配置加载 / 保存 ──────────────────────────────────────────────

    def _load_config(self):
        cfg = _read_config()
        for key, (ftype, var) in self._widgets.items():
            val = _get_nested(cfg, key.split("."))
            if ftype == "bool":
                var.set(bool(val))
            elif ftype == "int":
                var.set(str(int(val)) if val is not None else "")
            elif ftype == "float":
                var.set(str(float(val)) if val is not None else "")
            else:
                var.set(str(val) if val is not None else "")

        chrome_path = _get_nested(cfg, ["shopping", "chrome_path"])
        self._chrome_path_var.set(str(chrome_path) if chrome_path else "")
        self._on_browser_type_changed()

    def _on_save(self):
        try:
            cfg = _read_config()
            for key, (ftype, var) in self._widgets.items():
                raw = var.get()
                if ftype == "bool":
                    val = bool(var.get())
                elif ftype == "int":
                    try:
                        val = int(raw) if raw else 0
                    except ValueError:
                        val = 0
                elif ftype == "float":
                    try:
                        val = float(raw) if raw else 0.0
                    except ValueError:
                        val = 0.0
                else:
                    val = raw
                _set_nested(cfg, key.split("."), val)

            browser_type = cfg.get("shopping", {}).get(
                "chrome_browser_type", "")
            if browser_type == "自定义路径":
                _set_nested(cfg, ["shopping", "chrome_path"],
                            self._chrome_path_var.get().strip())
            else:
                _set_nested(cfg, ["shopping", "chrome_path"], "")

            _write_config(cfg)

            # 写入验证
            verify = _read_config()
            vt = _get_nested(verify, ["shopping", "chrome_browser_type"])
            if vt != browser_type:
                raise RuntimeError(
                    f"写入验证失败: 期望 {browser_type}，读到 {vt}")
            messagebox.showinfo("保存", "配置已保存", parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
        finally:
            self.destroy()

    def _on_reset(self):
        if not messagebox.askyesno("确认", "恢复所有设置为默认值？",
                                   parent=self):
            return
        _reset_config()
        self._load_config()


# ── 主窗口 ────────────────────────────────────────────────────────────────


class ModernApp:
    """Video2Shop 主应用 — 现代卡片式界面。"""

    # 日志关键词黑名单 — 过滤内部调试细节
    _LOG_BLACKLIST = [
        "frame_00", "等待分析状态", "批量上传", "输入框",
        "点击 div 类型发送按钮", "等待搜索结果",
        "查找'加入购物车'按钮", "选择器未命中", "JS 查找加购按钮",
        "尝试连接 Chrome", "CDP 连接失败", "CDP 连接成功",
        "等待 Chrome 就绪", "networkidle", "搜索关键词",
        "等待商品列表", "等待加购按钮渲染", "页面网络已空闲",
        "找到加购按钮", "加购成功 (尝试", "搜索加购异常",
        "_addCart_", "debug_no_add_button", "debug_page.html",
        "outerHTML", "浏览器的可执行文件", "可执行文件:",
        "用户目录:", "调试端口:",
    ]

    _SUPPRESS_LOGGERS = frozenset({
        "easyocr", "PIL", "PIL.Image", "cv2", "numpy",
        "urllib3", "requests", "charset_normalizer",
        "playwright", "pw.connection", "pw.browser",
        "matplotlib", "torch", "tensorflow",
    })

    def __init__(self):
        # ── 窗口 ──────────────────────────────────────────────────────
        if HAS_TTKB:
            self.root = ttkb.Window(themename="litera")
        else:
            self.root = tk.Tk()

        self.root.title(f"Video2Shop v{__version__}")
        self.root.geometry("1050x700")
        self.root.minsize(900, 550)

        # 状态
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._recipe_result: Optional[dict] = None
        self._jd_handler = None

        # 网格权重 — 右侧主区域可弹性伸缩
        self.root.grid_rowconfigure(0, weight=1)   # 主内容
        self.root.grid_rowconfigure(1, weight=0)   # 状态栏
        self.root.grid_columnconfigure(0, weight=0)  # 侧边栏固定
        self.root.grid_columnconfigure(1, weight=1)  # 主区域弹性

        self._build_sidebar()
        self._build_main_area()
        self._build_status_bar()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 启动时自动检查（可在设置中关闭）
        cfg = _read_config()
        if cfg.get("gui", {}).get("startup_check", True):
            self.root.after(500, self._run_preflight)

    # ── 侧边栏 ────────────────────────────────────────────────────────

    def _build_sidebar(self):
        """左侧面板：Logo + URL 输入 + 按钮 + 进度。"""
        sidebar = ttk.Frame(self.root, padding=12)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(4, 0), pady=4)
        sidebar.grid_propagate(False)
        sidebar.configure(width=280)

        # Logo
        title_frame = ttk.Frame(sidebar)
        title_frame.pack(fill="x", pady=(4, 16))
        ttk.Label(title_frame, text="🎬 Video2Shop",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(title_frame, text="B站视频 → 配方 → 京东加购",
                  foreground="gray", font=("", 8)).pack(anchor="w")

        # ── URL 输入卡片 ─────────────────────────────────────────────
        card = (ttkb.Frame if HAS_TTKB else ttk.Frame)
        url_card = card(sidebar, padding=12)
        if HAS_TTKB:
            url_card.configure(bootstyle="light")
        url_card.pack(fill="x", pady=(0, 12))

        ttk.Label(url_card, text="视频链接或 BV 号",
                  font=("", 9, "bold")).pack(anchor="w", pady=(0, 6))

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_card, textvariable=self.url_var,
                                   font=("", 10))
        self.url_entry.pack(fill="x", pady=(0, 8))
        self.url_entry.bind("<Return>", lambda e: self._start_pipeline())

        # 按钮行
        btn_row = ttk.Frame(url_card)
        btn_row.pack(fill="x")

        if HAS_TTKB:
            self.btn_start = ttk.Button(
                btn_row, text="▶ 开始提取", bootstyle="primary",
                command=self._start_pipeline)
            self.btn_stop = ttk.Button(
                btn_row, text="■ 停止", bootstyle="danger",
                command=self._stop_pipeline)
        else:
            self.btn_start = ttk.Button(
                btn_row, text="▶ 开始提取",
                command=self._start_pipeline)
            self.btn_stop = ttk.Button(
                btn_row, text="■ 停止",
                command=self._stop_pipeline)

        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop.pack(side="left", fill="x", expand=True)
        self.btn_stop.configure(state="disabled")

        # 准备工作 + 设置按钮
        self._preflight_btn = ttk.Button(
            sidebar, text="🔧 准备工作",
            command=self._run_preflight)
        self._preflight_btn.pack(fill="x", pady=(0, 6))

        if HAS_TTKB:
            ttk.Button(sidebar, text="⚙ 设置", bootstyle="secondary",
                       command=self._open_settings).pack(
                fill="x", pady=(0, 16))
        else:
            ttk.Button(sidebar, text="⚙ 设置",
                       command=self._open_settings).pack(
                fill="x", pady=(0, 16))

        # 进度条
        self.progress = ttk.Progressbar(sidebar, mode="indeterminate",
                                        length=240)
        self.progress.pack(fill="x", pady=(0, 8))

        # 用时
        self._elapsed_var = tk.StringVar(value="")
        ttk.Label(sidebar, textvariable=self._elapsed_var,
                  foreground="gray", font=("", 8)).pack()

    # ── 主区域 (Notebook) ────────────────────────────────────────────

    def _build_main_area(self):
        """右侧：Notebook 标签页 (配方清单 + 执行日志)。"""
        main = ttk.Frame(self.root, padding=4)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=4)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self._build_recipe_tab()
        self._build_log_tab()

        # 默认选中配方页
        self.notebook.select(0)

    def _build_recipe_tab(self):
        """配方清单标签页：左右两列卡片。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="  📋 配方清单  ")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=0)

        # 左右面板
        self.ingredients_panel = ScrollableCheckPanel(
            tab, title="🥘 食材清单 (0)")
        self.ingredients_panel.grid(
            row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)

        self.tools_panel = ScrollableCheckPanel(
            tab, title="🔧 工具清单 (0)")
        self.tools_panel.grid(
            row=0, column=1, sticky="nsew", padx=(4, 0), pady=2)

        # 操作栏
        action_bar = ttk.Frame(tab)
        action_bar.grid(row=1, column=0, columnspan=2, sticky="ew",
                        pady=(8, 0))

        if HAS_TTKB:
            self.btn_shop = ttk.Button(
                action_bar, text="🛒 加购未选中物品",
                bootstyle="success",
                command=self._start_shopping)
        else:
            self.btn_shop = ttk.Button(
                action_bar, text="🛒 加购未选中物品",
                command=self._start_shopping)

        self.btn_shop.pack(side="left", padx=2)
        self.btn_shop.configure(state="disabled")

        ttk.Button(action_bar, text="↺ 重置所有勾选",
                   command=self._reset_all_checked).pack(
            side="left", padx=8)

        self.shop_status_var = tk.StringVar(value="")
        ttk.Label(action_bar, textvariable=self.shop_status_var,
                  foreground="#e4393c",
                  font=("", 9, "bold")).pack(side="right", padx=8)

    def _build_log_tab(self):
        """执行日志标签页：深色主题日志区域。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="  📝 执行日志  ")
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(tab, text="日志输出", padding=4)
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        log_bg = "#1e1e1e"
        log_fg = "#d4d4d4"

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word",
            font=("Cascadia Code", 9),
            bg=log_bg, fg=log_fg,
            insertbackground=log_fg,
            relief="flat", borderwidth=0,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        log_menu = tk.Menu(self.log_text, tearoff=0)
        log_menu.add_command(label="清空", command=self._clear_log)
        log_menu.add_command(label="复制全部", command=self._copy_log)
        self.log_text.bind(
            "<Button-3>",
            lambda e: log_menu.tk_popup(e.x_root, e.y_root))

    # ── 状态栏 ────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = ttk.Frame(self.root, relief="sunken", padding=(8, 3))
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self.status_var = tk.StringVar(value="● 就绪")
        ttk.Label(bar, textvariable=self.status_var,
                  anchor="w", padding=(4, 0)).pack(side="left")

        self._summary_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._summary_var,
                  anchor="e", foreground="gray",
                  font=("", 8)).pack(side="right", padx=8)

    # ── 日志系统 ──────────────────────────────────────────────────────

    # 用于剥离日志前缀的正则: "HH:MM:SS [LEVEL] name: "
    _LOG_PREFIX_RE = re.compile(r"^[\d:,]+\s+\[\w+\]\s+[\w.]+:\s*")

    def _append_log(self, msg: str):
        """线程安全 — 子线程调用。过滤噪声日志并剥离技术前缀。"""
        # 1. 解析 logger 名称并过滤
        m = re.match(r"[\d:,]+\s+\[(\w+)\]\s+([\w.]+):", msg)
        if m:
            level, name = m.group(1), m.group(2)
            if level == "DEBUG":
                return
            if name in self._SUPPRESS_LOGGERS:
                return
            if name.split(".")[0] in self._SUPPRESS_LOGGERS:
                return

        # 2. 关键词黑名单（在剥离前缀前检查原始消息）
        for kw in self._LOG_BLACKLIST:
            if kw in msg:
                return

        # 3. 剥离技术前缀 — "HH:MM:SS [LEVEL] module: " → 纯消息
        clean = self._LOG_PREFIX_RE.sub("", msg)

        # 4. 推断状态（基于清理后的消息）
        hint = None
        if "下载" in clean:
            hint = "正在下载视频..."
        elif "OCR" in clean or "抽帧" in clean:
            hint = "正在处理视频帧..."
        elif "DeepSeek" in clean or "分析" in clean:
            hint = "正在 AI 分析..."
        elif "加购" in clean:
            hint = "正在加购..."

        self.root.after(0, self._append_log_ui, clean, hint)

    def _append_log_ui(self, msg: str, hint: str = None):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        if hint:
            self.status_var.set(f"● {hint}")
            self.root.title(f"Video2Shop — {hint}")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end-1c"))

    # ── 管道控制 ──────────────────────────────────────────────────────

    def _start_pipeline(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入 B站视频链接或 BV 号")
            return

        self._stop_event.clear()
        self._recipe_result = None
        self.ingredients_panel.clear()
        self.tools_panel.clear()
        self._update_shop_ui()
        self._summary_var.set("")
        self._elapsed_var.set("")

        self._set_running(True)
        self._append_log_ui("═" * 50)
        self._append_log_ui("▶ 管道启动中...")
        self.status_var.set("● 运行中")
        self.root.title("Video2Shop — 运行中")
        self.progress.start(8)
        self.notebook.select(0)  # 切到配方页

        self._pipe_start = time.time()

        self._worker_thread = threading.Thread(
            target=self._run_pipeline_thread, args=(url,), daemon=True)
        self._worker_thread.start()

    def _run_pipeline_thread(self, url: str):
        from pipeline import run_pipeline
        result = run_pipeline(
            url=url,
            config_path=str(CONFIG_PATH),
            log_callback=self._append_log,
            stop_event=self._stop_event,
        )
        self.root.after(0, self._on_pipeline_done, result)

    def _on_pipeline_done(self, result: dict):
        self._set_running(False)
        self.progress.stop()

        elapsed = time.time() - self._pipe_start if hasattr(
            self, '_pipe_start') else 0
        self._elapsed_var.set(
            f"用时 {elapsed:.1f}s" if elapsed else "")

        if result["success"]:
            self._append_log_ui("═" * 50)
            self._append_log_ui("✓ 管道成功完成")
            self.status_var.set("● 提取完成")
            self.root.title("Video2Shop — 提取完成")
            self._recipe_result = result
            self._populate_results(
                result["ingredients"], result["tools"])
        else:
            err = result.get("error", "未知错误")
            self._append_log_ui(f"✗ 管道失败: {err}")
            self.status_var.set("● 失败")
            self.root.title("Video2Shop — 失败")

    def _stop_pipeline(self):
        self._append_log_ui("⏸ 正在停止...")
        self._stop_event.set()

    def _set_running(self, running: bool):
        if running:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.url_entry.configure(state="disabled")
            self.btn_shop.configure(state="disabled")
        else:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.url_entry.configure(state="normal")

    # ── 配方结果展示 ──────────────────────────────────────────────────

    def _populate_results(self, ingredients: list, tools: list):
        self.ingredients_panel.populate(ingredients, is_ingredient=True)
        self.tools_panel.populate(tools, is_ingredient=False)
        self._update_shop_ui()

    def _reset_all_checked(self):
        self.ingredients_panel._toggle_all(True)
        self.tools_panel._toggle_all(True)
        self._update_shop_ui()

    def _update_shop_ui(self):
        u_ing = len(self.ingredients_panel.unchecked_items)
        u_tool = len(self.tools_panel.unchecked_items)
        total_uncheck = u_ing + u_tool
        total = self.ingredients_panel.total + self.tools_panel.total

        if total > 0:
            self.btn_shop.configure(state="normal")
            self.shop_status_var.set(
                f"已拥有 {total - total_uncheck}/{total}，"
                f"待加购 {total_uncheck} 件")
            self._summary_var.set(
                f"📋 {total} 项 | 待加购 {total_uncheck} 件")
        else:
            self.btn_shop.configure(state="disabled")
            self.shop_status_var.set("")
            self._summary_var.set("")

    # ── 京东加购 ──────────────────────────────────────────────────────

    def _start_shopping(self):
        unchecked = (self.ingredients_panel.unchecked_items +
                     self.tools_panel.unchecked_items)
        if not unchecked:
            messagebox.showinfo("提示", "所有物品已勾选，无需加购")
            return

        self.btn_shop.configure(state="disabled")
        self.shop_status_var.set("正在加购...")
        self._append_log_ui(f"🛒 开始加购 {len(unchecked)} 件商品...")
        self.status_var.set("● 正在加购...")
        self.root.title("Video2Shop — 正在加购...")
        self._stop_event.clear()

        threading.Thread(target=self._run_shopping_thread,
                         args=(unchecked,), daemon=True).start()

    def _run_shopping_thread(self, items: list):
        from shopping_platform import JdHandler

        cfg = _read_config().get("shopping", {})
        chrome_path = cfg.get("chrome_path", "") or None
        browser_type = cfg.get("chrome_browser_type", "")
        if browser_type == "自定义路径":
            browser_type = None

        handler = JdHandler(
            debug_port=cfg.get("debug_port", 9222),
            auto_launch=cfg.get("auto_launch", True),
            close_browser_on_exit=cfg.get("close_browser_on_exit", False),
            search_timeout=cfg.get("search_timeout", 10000),
            add_cart_retry=cfg.get("add_cart_retry", 2),
            add_cart_delay=cfg.get("add_cart_delay", 0.5),
            click_retry=cfg.get("click_retry", 1),
            search_wait_after=cfg.get("search_wait_after", 1.0),
            retry_on_failure=cfg.get("retry_on_failure", True),
            chrome_path=chrome_path,
            browser_type=browser_type if browser_type else None,
        )

        success = 0
        try:
            self._append_log("连接浏览器并登录京东...")
            handler.login()
            for i, kw in enumerate(items):
                if self._stop_event.is_set():
                    self._append_log("⏸ 用户取消加购")
                    break
                self._append_log(
                    f"[{i+1}/{len(items)}] 加购: {kw}")
                if handler.search_and_add(kw):
                    success += 1
                if (i < len(items) - 1
                        and not self._stop_event.is_set()):
                    time.sleep(1.0)
            handler.open_cart_page()
            self._append_log(
                f"✓ 加购完成: {success}/{len(items)} 成功")
        except Exception as e:
            self._append_log(f"✗ 加购异常: {e}")
        finally:
            self._jd_handler = handler
            self.root.after(0, self._on_shopping_done,
                            success, len(items))

    def _on_shopping_done(self, success: int, total: int):
        self.btn_shop.configure(state="normal")
        self.shop_status_var.set(
            f"加购完成: {success}/{total} 成功")
        self.status_var.set("● 就绪")
        self.root.title("Video2Shop — 空闲")

    # ── 设置 ──────────────────────────────────────────────────────────

    def _open_settings(self):
        SettingsDialog(self.root)

    def _run_preflight(self):
        """手动触发启动前检查。"""
        self._preflight_btn.configure(state="disabled")
        self._append_log_ui("🔧 启动检查中...")
        self.status_var.set("● 正在检查...")

        def _worker():
            from preflight import run_preflight
            def cb(name, status, detail):
                icon = {"ok": "✓", "missing": "⚠", "failed": "✗", "skipped": "—"}
                self.root.after(0, self._append_log_ui,
                                f"  {icon.get(status.value, '?')} {name}: {detail}")
            results = run_preflight(
                config_path=str(CONFIG_PATH),
                status_callback=cb,
            )
            ok_count = sum(1 for s in results.values() if s == CheckStatus.OK)
            total = len(results)
            self.root.after(0, self._on_preflight_done, ok_count, total)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_preflight_done(self, ok: int, total: int):
        self._preflight_btn.configure(state="normal")
        self.status_var.set("● 就绪")
        if ok == total:
            self._append_log_ui(f"✓ 准备工作完成 ({ok}/{total})，可以开始使用")
        else:
            self._append_log_ui(
                f"⚠ 准备工作完成 ({ok}/{total})，"
                "缺少的项已打开浏览器，请在浏览器窗口中完成登录"
            )

    # ── 关闭 ──────────────────────────────────────────────────────────

    def _on_close(self):
        if self._worker_thread and self._worker_thread.is_alive():
            if messagebox.askyesno("确认",
                                   "任务正在运行中，确定要退出吗？"):
                self._stop_event.set()
            else:
                return
        if self._jd_handler:
            try:
                self._jd_handler.close()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── 入口 ──────────────────────────────────────────────────────────────────


def main():
    app = ModernApp()
    app.run()


if __name__ == "__main__":
    main()
