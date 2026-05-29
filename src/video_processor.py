"""
视频处理模块：B站视频下载（BiliDownloader）、抽帧（OpenCV）、OCR筛选。
无系统级 ffmpeg 依赖，支持 JSON 文本回退模式。
"""

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class FfmpegNotNeededError(Exception):
    """因为已用 durl 或 JSON 模式，不需要 ffmpeg。保留此类用于兼容旧代码。"""
    pass


class VideoProcessor:
    """负责视频/JSON下载、关键帧抽取、OCR文字过滤。"""

    def __init__(self, config: dict):
        self.config = config
        self.video_cfg = config.get("video", {})
        self.ocr_cfg = config.get("ocr", {})

        self.download_dir = Path(self.video_cfg.get("download_dir", "./temp/videos"))
        self.frames_dir = Path(self.video_cfg.get("frames_dir", "./temp/frames"))
        self.frame_interval = self.video_cfg.get("frame_interval", 5)
        self.use_scene_detection = self.video_cfg.get("use_scene_detection", True)
        self.max_frames = self.video_cfg.get("max_frames", 20)
        self.keep_temp = self.video_cfg.get("keep_temp_files", False)

        self.min_chinese = self.ocr_cfg.get("min_chinese_chars", 20)
        # 渐进式宽松阈值：严格筛选无结果时自动降级使用
        self.min_chinese_relaxed = max(3, self.min_chinese // 4)
        self.ocr_languages = self.ocr_cfg.get("languages", ["ch_sim", "en"])

        self._ocr_reader = None

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            try:
                import easyocr
            except ImportError:
                raise ImportError(
                    "缺少 OCR 识别组件，程序安装可能不完整。\n"
                    "请重新运行 auto_build.py 构建，或手动: pip install torch easyocr"
                )

            logger.info("正在加载 easyocr 中文模型（首次运行会下载约 100MB）...")
            self._ocr_reader = easyocr.Reader(self.ocr_languages, gpu=False)
            logger.info("easyocr 模型加载完成")
        return self._ocr_reader

    # ── 视频下载（使用 BiliDownloader）─────────────────────────────────────

    def download_video(
        self,
        url: str,
        cookies_path: Optional[str] = None,
        quality: int = 64,
    ) -> Optional[Path]:
        """使用 BiliDownloader 下载B站视频（durl优先，无需 ffmpeg）。"""
        self.download_dir.mkdir(parents=True, exist_ok=True)

        from bili_downloader import BiliDownloader

        dl = BiliDownloader(
            cookies_path=cookies_path,
            output_dir=str(self.download_dir),
            prefer_durl=True,  # 强制 durl 优先，完全不触发 ffmpeg
        )

        try:
            video_path = dl.download(url, quality=quality)
            logger.info(f"视频下载完成: {video_path}")
            return video_path
        except Exception as e:
            logger.error(f"视频下载失败: {e}")
            raise

    # ── JSON 文本回退模式 ────────────────────────────────────────────────

    def extract_text_from_json(self, json_path: str) -> str:
        """从 B站 导出的 JSON 文件中提取文本内容（评论/弹幕/简介）。

        支持的 JSON 格式:
          1. 篡改猴脚本导出: {"comments": [{"content": "..."}, ...], "danmaku": [...]}
          2. 简单评论列表: [{"content": "..."}, ...]
          3. 纯字符串数组: ["文本1", "文本2", ...]
          4. 任意含文本字段的 JSON

        返回: 合并后的文本字符串（用于后续 DeepSeek 文本API提取配方）
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = []

        def _extract(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, str):
                if len(obj) > 2:
                    texts.append(obj)
            elif isinstance(obj, dict):
                for key, val in obj.items():
                    if key in ("content", "text", "message", "desc", "description",
                               "title", "comment", "danmaku", "reply"):
                        if isinstance(val, str) and len(val) > 2:
                            texts.append(val)
                        elif isinstance(val, list):
                            for item in val:
                                _extract(item, depth + 1)
                    else:
                        _extract(val, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item, depth + 1)

        _extract(data)

        merged = "\n".join(texts)
        logger.info(f"从 JSON 提取了 {len(texts)} 段文本，共 {len(merged)} 字符")
        return merged

    def scan_json_files(self, directory: str = ".") -> List[Path]:
        """扫描目录下的 .json 文件，返回路径列表。"""
        scan_dir = Path(directory)
        json_files = sorted(scan_dir.glob("*.json"))
        if not json_files:
            logger.warning(f"目录 {directory} 下未找到 .json 文件")
        else:
            logger.info(f"找到 {len(json_files)} 个 JSON 文件: {[f.name for f in json_files]}")
        return json_files

    # ── 帧抽取 ───────────────────────────────────────────────────────────

    def extract_frames(self, video_path: Path) -> List[Path]:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        for f in self.frames_dir.glob("frame_*.jpg"):
            f.unlink()

        if self.use_scene_detection:
            frames = self._extract_by_opencv_scene_detection(video_path)
        else:
            frames = self._extract_by_interval(video_path)

        logger.info(f"共抽取 {len(frames)} 帧")
        return frames

    def _extract_by_opencv_scene_detection(self, video_path: Path) -> List[Path]:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        if duration <= 0 or total_frames == 0:
            cap.release()
            logger.warning("无法读取视频信息，回退到固定间隔抽帧")
            return self._extract_by_interval(video_path)

        scan_interval = int(fps / 2) if fps >= 2 else 1
        if scan_interval < 1:
            scan_interval = 1

        frames = []
        prev_hist = None
        threshold = 0.45

        frame_idx = 0
        while frame_idx < total_frames and len(frames) < self.max_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                frame_idx += scan_interval
                continue

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            hist = cv2.normalize(hist, hist).flatten()

            is_scene_change = False
            if prev_hist is not None:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if corr < threshold:
                    is_scene_change = True
            else:
                is_scene_change = True

            if is_scene_change:
                frame_path = self.frames_dir / f"frame_{len(frames):04d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frames.append(frame_path)
                prev_hist = hist

            frame_idx += scan_interval

        cap.release()

        if len(frames) <= 1:
            logger.warning("场景检测只找到少量镜头变化，补充固定间隔抽帧")
            interval_frames = self._extract_by_interval(video_path)
            existing_names = {f.name for f in frames}
            for fp in interval_frames:
                if fp.name not in existing_names and len(frames) < self.max_frames:
                    frames.append(fp)
                    existing_names.add(fp.name)

        return frames

    def _extract_by_interval(self, video_path: Path) -> List[Path]:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        if duration <= 0:
            cap.release()
            logger.error("无法读取视频时长")
            return []

        interval_frames = int(fps * self.frame_interval)
        expected_count = int(duration / self.frame_interval)
        if expected_count > self.max_frames:
            interval_frames = int(total_frames / self.max_frames)
        if interval_frames < 1:
            interval_frames = 1

        frames = []
        for i, frame_pos in enumerate(range(0, total_frames, interval_frames)):
            if len(frames) >= self.max_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if ret:
                frame_path = self.frames_dir / f"frame_{i:04d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frames.append(frame_path)

        cap.release()
        return frames

    # ── OCR 筛选 ─────────────────────────────────────────────────────────

    def filter_frames_by_text(
        self, frame_paths: List[Path], threshold: Optional[int] = None
    ) -> List[Path]:
        """对每帧进行OCR，只保留中文字符数 >= threshold 的图片。

        参数:
            frame_paths: 帧图片路径列表
            threshold: 中文字符阈值，默认使用 self.min_chinese
        """
        if not frame_paths:
            return []

        if threshold is None:
            threshold = self.min_chinese

        reader = self._get_ocr_reader()
        filtered = []

        logger.info(
            f"正在对 {len(frame_paths)} 帧进行 OCR 文字筛选（阈值: >= {threshold} 个中文字符）..."
        )
        for i, fp in enumerate(frame_paths):
            try:
                results = reader.readtext(str(fp), detail=0)
                text = "".join(results)
                chinese_count = len(re.findall(r"[一-鿿]", text))

                if chinese_count >= threshold:
                    logger.info(f"  frame_{i:04d}: {chinese_count} 个中文字符 ✓")
                    filtered.append(fp)
                else:
                    logger.info(f"  frame_{i:04d}: {chinese_count} 个中文字符 ✗")

            except Exception as e:
                logger.warning(f"  frame_{i:04d}: OCR 失败 - {e}")

        logger.info(f"OCR 筛选完成：{len(filtered)}/{len(frame_paths)} 帧通过")

        # 严格模式无结果 → 自动降级到宽松阈值重试
        if len(filtered) == 0 and threshold > self.min_chinese_relaxed:
            logger.warning(
                f"严格阈值 ({threshold}) 未筛选到任何帧，"
                f"自动降级为宽松阈值 ({self.min_chinese_relaxed}) 重试..."
            )
            filtered = self.filter_frames_by_text(frame_paths, self.min_chinese_relaxed)

        return filtered

    # ── 清理 ─────────────────────────────────────────────────────────────

    def cleanup_video(self, video_path: Optional[Path] = None):
        if self.keep_temp:
            return
        if video_path and video_path.exists():
            video_path.unlink()
            logger.info(f"已删除视频文件: {video_path}")

    def cleanup_frames(self, frame_paths: Optional[List[Path]] = None):
        if self.keep_temp:
            return
        if frame_paths:
            for fp in frame_paths:
                if fp.exists():
                    fp.unlink()
        if self.frames_dir.exists():
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            logger.info("已清理帧图片目录")

    def cleanup_all(self):
        if self.keep_temp:
            return
        if self.download_dir.exists():
            shutil.rmtree(self.download_dir, ignore_errors=True)
            logger.info("已清理临时目录")

    def process(
        self,
        url: str,
        cookies_path: Optional[str] = None,
        quality: int = 64,
    ) -> List[Path]:
        """完整视频处理流程：下载 → 抽帧 → OCR筛选。

        如果 OCR 筛选后无帧（含宽松模式重试后仍为 0），
        返回空列表并输出清晰的 JSON 回退引导，不抛异常。
        """
        video_path = self.download_video(url, cookies_path=cookies_path, quality=quality)
        try:
            frame_paths = self.extract_frames(video_path)
            if not frame_paths:
                logger.error("未能从视频中抽取任何帧")
                return []

            filtered = self.filter_frames_by_text(frame_paths)

            if not filtered:
                logger.warning(
                    "=" * 50 + "\n"
                    "OCR 未从视频帧中筛选到包含足够文字的图片。\n"
                    "建议以下替代方案：\n"
                    "  1. 降低 OCR 阈值: 在 config.yaml 中设置 ocr.min_chinese_chars: 10\n"
                    "  2. 使用 JSON 回退模式:\n"
                    "     python main.py --json <导出的B站评论.json>\n"
                    "  3. 自动扫描 JSON:\n"
                    "     python main.py --url \"URL\" --scan-json\n"
                    "  4. 检查视频是否包含配方表格/步骤文字画面\n"
                    + "=" * 50
                )

            return filtered
        finally:
            self.cleanup_video(video_path)
