"""
共享后端管道 — 视频分析 + 配方提取。

提供 run_pipeline() 函数，供命令行 (main.py)、桌面 GUI (gui.py)
和 Web 前端 (web_app.py) 共同调用，避免重复实现核心逻辑。
"""

import logging
import re
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

import yaml

logger = logging.getLogger("pipeline")


# ── 日志回调处理器 ──────────────────────────────────────────────────────

class CallbackHandler(logging.Handler):
    """将 logging 消息实时转发到用户提供的回调函数。"""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "%H:%M:%S",
        ))

    def emit(self, record):
        try:
            self.callback(self.format(record))
        except Exception:
            pass


# ── 工具函数 ────────────────────────────────────────────────────────────

def load_config(config_path: str = "config/config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if re.match(r"^BV[a-zA-Z0-9]+$", url):
        return f"https://www.bilibili.com/video/{url}"
    if "b23.tv" in url:
        if not url.startswith("http"):
            url = "https://" + url
        return url
    return url


# ── 主流程 ──────────────────────────────────────────────────────────────

def run_pipeline(
    url: str,
    config_path: str = "config/config.yaml",
    log_callback: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    cookies_path: Optional[str] = None,
    quality: int = 64,
) -> Dict:
    """运行完整的视频配方提取管道。

    Args:
        url:             B站视频链接或 BV 号
        config_path:     配置文件路径
        log_callback:    可选回调，接收格式化日志字符串（线程安全要求由调用方保证）
        stop_event:      可选事件，设置后尽快中断管道
        cookies_path:    Netscape 格式 cookies 路径
        quality:         视频画质 (16/32/64/80)

    Returns:
        {"success": bool, "ingredients": [...], "tools": [...], "error": "..."}
    """
    if stop_event is None:
        stop_event = threading.Event()

    # ── 安装日志回调 ──────────────────────────────────────────────────
    handler = None
    if log_callback:
        handler = CallbackHandler(log_callback)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)  # 确保 INFO 消息能传播到 handler
        root_logger.addHandler(handler)

        # 抑制第三方库的冗余日志（仅影响回调输出，不影响文件日志）
        _noisy_libs = [
            "easyocr", "PIL", "cv2", "numpy", "matplotlib",
            "urllib3", "requests", "charset_normalizer",
            "playwright", "tensorflow", "torch",
        ]
        for lib in _noisy_libs:
            logging.getLogger(lib).setLevel(logging.WARNING)

    try:
        config = load_config(config_path)
        normalized = normalize_url(url)

        logger.info("=" * 50)
        logger.info(f"Video2Shop 管道启动")
        logger.info(f"  目标视频: {normalized}")
        logger.info("=" * 50)

        if stop_event.is_set():
            return _fail("用户取消")

        # ── 步骤 1: 视频下载 + 抽帧 + OCR ─────────────────────────────
        logger.info("步骤 1/2: 视频下载与抽帧")

        from video_processor import VideoProcessor
        processor = VideoProcessor(config)

        filtered_frames = None
        try:
            filtered_frames = processor.process(
                normalized, cookies_path=cookies_path, quality=quality
            )
        except Exception as e:
            logger.error(f"视频处理异常: {e}")

        # ── 步骤 1 失败 → JSON 回退 ───────────────────────────────────
        if not filtered_frames:
            logger.warning("未从视频中提取到有效帧，尝试 JSON 回退...")
            json_files = processor.scan_json_files()
            if json_files:
                json_files.sort(key=lambda f: f.stat().st_size, reverse=True)
                logger.info(f"找到 {len(json_files)} 个 JSON 文件，使用 {json_files[0].name}")
                text = processor.extract_text_from_json(str(json_files[0]))
                if text and len(text) >= 10:
                    try:
                        from recipe_extractor import RecipeExtractor
                        extractor = RecipeExtractor(config)
                        recipe = extractor.extract_from_text(text)
                    except ValueError as e:
                        processor.cleanup_all()
                        return _fail(str(e))
                else:
                    processor.cleanup_all()
                    return _fail("JSON 文件中提取的文本内容太少")
            else:
                processor.cleanup_all()
                msg = (
                    "未从视频中筛选到包含足够文字的帧。\n"
                    "建议：尝试 --interval 3 减小抽帧间隔；"
                    "或使用 --json <文件.json> 从评论数据提取。"
                )
                return _fail(msg)

        else:
            if stop_event.is_set():
                processor.cleanup_all()
                return _fail("用户取消")

            max_frames = config.get("video", {}).get("max_frames", 5)
            logger.info(f"筛选出 {len(filtered_frames)} 帧，最多使用 {max_frames} 张")

            # ── 步骤 2: DeepSeek 网页版配方提取 ────────────────────────
            logger.info("步骤 2/2: DeepSeek 网页版配方提取")

            from deepseek_web_analyzer import analyze_frames_with_deepseek_web
            recipe = analyze_frames_with_deepseek_web(
                filtered_frames, config=config, max_images=max_frames,
            )

            processor.cleanup_frames(filtered_frames)

        if stop_event.is_set():
            processor.cleanup_all()
            return _fail("用户取消")

        # ── 验证结果 ──────────────────────────────────────────────────
        if recipe is None or "error" in recipe:
            error_msg = recipe.get("message", "未知错误") if recipe else "流程未返回结果"
            logger.error(f"配方提取失败: {error_msg}")
            processor.cleanup_all()
            return _fail(error_msg)

        ingredients = recipe.get("ingredients", [])
        tools = recipe.get("tools", [])

        if not ingredients and not tools:
            processor.cleanup_all()
            return _fail("未提取到任何食材或工具，请更换视频或数据源")

        logger.info(f"提取完成: {len(ingredients)} 种食材, {len(tools)} 个工具")
        for ing in ingredients:
            logger.info(f"  食材: {ing['name']} — {ing.get('amount', '适量')}")
        for tool in tools:
            logger.info(f"  工具: {tool}")

        processor.cleanup_all()
        logger.info("管道完成")

        return {
            "success": True,
            "ingredients": ingredients,
            "tools": tools,
        }

    finally:
        if handler:
            root = logging.getLogger()
            root.removeHandler(handler)


def _fail(message: str) -> Dict:
    logger.error(message)
    return {"success": False, "error": message, "ingredients": [], "tools": []}
