#!/usr/bin/env python3
"""
B站视频配方自动提取 + 京东购物车助手 — 命令行入口。

用法:
    python main.py --url "https://www.bilibili.com/video/BV1xxx"
    python main.py --url "BV1xxx" --cookies cookies.txt
    python main.py --url "BV1xxx" --scan-json

核心逻辑位于 pipeline.py，本文件仅提供命令行参数解析和结果展示。
"""

import argparse
import logging
import sys

from pipeline import load_config, normalize_url, run_pipeline


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)


def parse_args():
    parser = argparse.ArgumentParser(
        description="B站视频配方自动提取 + 京东购物车助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --url "https://www.bilibili.com/video/BV1xxx"
  python main.py --url "BV1xxx" --cookies cookies.txt
  python main.py --url "BV1xxx" --scan-json --verbose
        """,
    )
    parser.add_argument("--url", "-u", default=None, help="B站视频链接（支持完整URL或BV号）")
    parser.add_argument("--json", "-j", default=None, help="JSON 文件路径（从B站导出的评论/弹幕数据）")
    parser.add_argument("--scan-json", action="store_true", help="自动扫描当前目录下的 .json 文件")
    parser.add_argument("--cookies", default=None, help="Netscape 格式的 cookies.txt 路径")
    parser.add_argument("--config", "-c", default="config/config.yaml", help="config file path")
    parser.add_argument("--keep-temp", action="store_true", help="保留临时文件（调试用）")
    parser.add_argument("--interval", "-i", type=int, default=None, help="抽帧间隔（秒）")
    parser.add_argument("--quality", "-q", type=int, default=64, help="视频画质 (16=360P, 32=480P, 64=720P, 80=1080P)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
    parser.add_argument("--port", "-p", type=int, default=None, help="Web 服务器端口 (默认: 5000)")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("main")

    # 验证参数
    if not args.url and not args.json and not args.scan_json:
        log.error("必须提供 --url、--json 或 --scan-json")
        sys.exit(1)

    # 加载配置
    config = load_config(args.config)
    if args.keep_temp:
        config.setdefault("video", {})["keep_temp_files"] = True
    if args.interval is not None:
        config.setdefault("video", {})["frame_interval"] = args.interval
        config["video"]["use_scene_detection"] = False
    if args.port is not None:
        config.setdefault("web", {})["port"] = args.port

    # ── 纯 JSON 模式（不下载视频）─────────────────────────────────────
    if args.json:
        log.info(f"JSON 模式: {args.json}")
        from video_processor import VideoProcessor
        processor = VideoProcessor(config)
        text = processor.extract_text_from_json(args.json)
        if not text or len(text) < 10:
            log.error("JSON 文件中提取的文本内容太少")
            sys.exit(1)
        from recipe_extractor import RecipeExtractor
        try:
            extractor = RecipeExtractor(config)
        except ValueError as e:
            log.error(str(e))
            sys.exit(1)
        recipe = extractor.extract_from_text(text)
        if recipe is None or "error" in recipe:
            log.error(f"配方提取失败: {recipe.get('message', '未知错误') if recipe else '未知错误'}")
            sys.exit(1)
        ingredients = recipe.get("ingredients", [])
        tools = recipe.get("tools", [])

    elif args.scan_json:
        from video_processor import VideoProcessor
        processor = VideoProcessor(config)
        json_files = processor.scan_json_files()
        if not json_files:
            log.error("当前目录下未找到 .json 文件")
            sys.exit(1)
        json_files.sort(key=lambda f: f.stat().st_size, reverse=True)
        log.info(f"自动选择: {json_files[0]}")
        text = processor.extract_text_from_json(str(json_files[0]))
        if not text or len(text) < 10:
            log.error("JSON 文本内容不足")
            sys.exit(1)
        from recipe_extractor import RecipeExtractor
        try:
            extractor = RecipeExtractor(config)
        except ValueError as e:
            log.error(str(e))
            sys.exit(1)
        recipe = extractor.extract_from_text(text)
        if recipe is None or "error" in recipe:
            log.error("配方提取失败")
            sys.exit(1)
        ingredients = recipe.get("ingredients", [])
        tools = recipe.get("tools", [])

    else:
        # ── 标准视频管道 ──────────────────────────────────────────────
        result = run_pipeline(
            url=args.url,
            config_path=args.config,
            log_callback=None,
            cookies_path=args.cookies,
            quality=args.quality,
        )

        if not result["success"]:
            log.error(f"管道失败: {result.get('error', '未知错误')}")
            sys.exit(1)

        ingredients = result["ingredients"]
        tools = result["tools"]

    # ── 展示结果并启动 Web 交互界面 ───────────────────────────────────
    log.info(f"提取完成: {len(ingredients)} 种食材, {len(tools)} 个工具")

    from web_interface import WebServer
    server = WebServer(config)
    server.set_recipe_data(ingredients, tools)

    try:
        server.start()
    except KeyboardInterrupt:
        log.info("用户中断，正在退出...")
    finally:
        server.cleanup()

    log.info("再见！")


if __name__ == "__main__":
    main()
