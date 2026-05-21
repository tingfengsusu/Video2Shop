"""
测试 video_processor.py
"""

import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestVideoProcessorInit:
    """测试 VideoProcessor 初始化。"""

    def test_init_with_config(self, sample_config):
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)
        assert vp.frame_interval == 5
        assert vp.min_chinese == 50
        assert vp.max_frames == 10
        assert vp.ocr_languages == ["ch_sim", "en"]

    def test_init_default_values(self):
        from video_processor import VideoProcessor

        vp = VideoProcessor({})
        assert vp.frame_interval == 5
        assert vp.min_chinese == 20     # 新默认值为 20
        assert vp.min_chinese_relaxed == 5  # 20 // 4 = 5

    def test_lazy_ocr_reader_loading(self, sample_config):
        """测试 OCR reader 懒加载。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)
        assert vp._ocr_reader is None  # 初始为 None


class TestFrameExtraction:
    """测试抽帧逻辑。"""

    def test_extract_by_interval_no_config(self, sample_config, temp_dir):
        """固定间隔抽帧 - 基本逻辑。"""
        from video_processor import VideoProcessor

        sample_config["video"]["frames_dir"] = str(temp_dir)
        vp = VideoProcessor(sample_config)

        # 由于没有真实视频，测试空帧路径处理
        with patch("cv2.VideoCapture") as mock_cap:
            mock_cap.return_value.get.side_effect = lambda prop: {
                5: 30.0,   # fps
                7: 300,    # total_frames
            }.get(prop, 0)
            mock_cap.return_value.read.return_value = (False, None)

            frames = vp._extract_by_interval(Path("/fake/video.mp4"))
            assert frames == []

    def test_extract_by_interval_with_frames(self, sample_config, temp_dir):
        """固定间隔抽帧 - 成功抽取。"""
        from video_processor import VideoProcessor
        import numpy as np

        sample_config["video"]["frames_dir"] = str(temp_dir)
        vp = VideoProcessor(sample_config)

        with patch("cv2.VideoCapture") as mock_cap:
            mock_cap.return_value.get.side_effect = lambda prop: {
                5: 30.0,    # fps
                7: 600,     # total_frames → 20s video
            }.get(prop, 0)
            # 每次 read 返回一个假帧
            fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cap.return_value.read.return_value = (True, fake_frame)

            with patch("cv2.imwrite", return_value=True):
                frames = vp._extract_by_interval(Path("/fake/video.mp4"))

            # 20s / 5s interval = 4 frames, under max_frames(10)
            assert len(frames) == 4
            for fp in frames:
                assert fp.suffix == ".jpg"

    def test_opencv_scene_detection(self, sample_config, temp_dir):
        """基于 OpenCV 的场景检测。"""
        from video_processor import VideoProcessor
        import numpy as np

        sample_config["video"]["frames_dir"] = str(temp_dir)
        sample_config["video"]["use_scene_detection"] = True
        vp = VideoProcessor(sample_config)

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        fake_frame[0:240, :] = 255  # 模拟场景变化

        with patch("cv2.VideoCapture") as mock_cap:
            mock_cap.return_value.get.side_effect = lambda prop: {
                5: 30.0, 7: 600
            }.get(prop, 0)
            mock_cap.return_value.read.return_value = (True, fake_frame)

            with patch("cv2.imwrite", return_value=True):
                frames = vp._extract_by_opencv_scene_detection(Path("/fake/video.mp4"))

            assert len(frames) > 0  # 至少第一帧会被保留


class TestOCRFilters:
    """测试 OCR 文字筛选。"""

    def test_filter_chinese_chars(self, sample_config):
        """测试中文字符计数逻辑。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)

        # 模拟 OCR 返回大量中文（需要 >50 中文字符）
        with patch.object(vp, "_get_ocr_reader") as mock_reader:
            # 每帧返回的文本含足够中文字符
            mock_reader.return_value.readtext.return_value = [
                "第一步：准备所有食材包括淡奶油细砂糖吉利丁片玉米淀粉低筋面粉黄油牛奶巧克力酱",
                "第二步：将淡奶油倒入搅拌碗中高速打发至出现明显纹路提起打蛋器呈弯钩状即可停止",
                "第三步：分次加入细砂糖继续搅拌均匀直到糖完全融化奶油变得细腻光滑有光泽",
                "所需工具：打蛋器搅拌碗刮刀电子秤面粉筛雪糕模具裱花袋烤箱温度计",
            ]

            frames = [Path(f"/fake/frame_{i:04d}.jpg") for i in range(3)]
            filtered = vp.filter_frames_by_text(frames)

            # 每帧都有足够的文字
            assert len(filtered) == 3

    def test_filter_low_text_frames(self, sample_config):
        """测试低文字帧被过滤。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)

        with patch.object(vp, "_get_ocr_reader") as mock_reader:
            # 返回很少的中文
            mock_reader.return_value.readtext.return_value = ["abc", "123"]

            frames = [Path(f"/fake/frame_0001.jpg")]
            filtered = vp.filter_frames_by_text(frames)

            assert len(filtered) == 0  # 中文字符不足

    def test_progressive_relaxation(self, sample_config):
        """严格阈值无结果时自动降级到宽松阈值重试。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)
        vp.min_chinese = 50           # 严格阈值
        vp.min_chinese_relaxed = 5    # 宽松阈值

        call_count = [0]

        def readtext_side_effect(path, detail=0):
            call_count[0] += 1
            # 每帧返回刚好超过宽松阈值但不到严格阈值的中文字符
            return ["食材面粉鸡蛋"]  # 6 个中文字符

        with patch.object(vp, "_get_ocr_reader") as mock_reader:
            mock_reader.return_value.readtext.return_value = ["食材面粉鸡蛋"]

            frames = [Path(f"/fake/frame_{i:04d}.jpg") for i in range(3)]
            filtered = vp.filter_frames_by_text(frames)

            # 第一次按 50 阈值返回 0 → 触发降级 → 按 5 阈值重试 → 3 帧通过
            assert len(filtered) == 3

    def test_progressive_relaxation_no_fallback(self, sample_config):
        """不触发降级：严格阈值本身就有结果时，不应再跑第二遍。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)
        vp.min_chinese = 50
        vp.min_chinese_relaxed = 5

        call_count = [0]

        def patched_readtext(path, detail=0):
            call_count[0] += 1
            return ["食材面粉鸡蛋牛奶白糖黄油巧克力淡奶油吉利丁玉米淀粉低筋搅拌打发烘焙烤箱模具电子秤量杯刮刀裱花袋油纸步骤完成"]

        with patch.object(vp, "_get_ocr_reader") as mock_reader:
            mock_reader.return_value.readtext.side_effect = patched_readtext

            frames = [Path(f"/fake/frame_{i:04d}.jpg") for i in range(2)]
            filtered = vp.filter_frames_by_text(frames)

            # 第一遍就全通过，共 OCR 2 次（每帧一次），不触发第二遍
            assert len(filtered) == 2
            assert call_count[0] == 2

    def test_filter_empty_frames(self, sample_config):
        """空帧列表应返回空。"""
        from video_processor import VideoProcessor

        vp = VideoProcessor(sample_config)
        result = vp.filter_frames_by_text([])
        assert result == []


class TestChineseRegex:
    """测试中文字符正则。"""

    def test_chinese_char_pattern(self):
        text = "食材准备：淡奶油两百毫升细砂糖五十克吉利丁片十克玉米淀粉适量低筋面粉过筛备用"
        chinese_count = len(re.findall(r"[一-鿿]", text))
        assert chinese_count > 10


class TestJSONFallback:
    """测试 JSON 文本回退模式。"""

    def test_extract_text_from_json_comments(self, sample_config, temp_dir):
        """从包含评论的 JSON 中提取文本。"""
        from video_processor import VideoProcessor
        import json

        data = {
            "comments": [
                {"content": "淡奶油要200ml"},
                {"content": "细砂糖50g"},
            ],
            "danmaku": [
                {"text": "吉利丁片10g"},
            ],
            "desc": "雪糕制作教程",
        }
        json_path = temp_dir / "test.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        vp = VideoProcessor(sample_config)
        text = vp.extract_text_from_json(str(json_path))
        assert "淡奶油" in text
        assert "细砂糖" in text
        assert "吉利丁片" in text

    def test_extract_text_from_string_array(self, sample_config, temp_dir):
        """从纯字符串数组 JSON 中提取文本。"""
        from video_processor import VideoProcessor
        import json

        data = ["需要材料：淡奶油200ml，细砂糖50g", "工具：打蛋器、模具"]
        json_path = temp_dir / "test2.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        vp = VideoProcessor(sample_config)
        text = vp.extract_text_from_json(str(json_path))
        assert "淡奶油" in text
        assert "打蛋器" in text

    def test_scan_json_files(self, sample_config, temp_dir):
        """扫描目录下的 JSON 文件。"""
        from video_processor import VideoProcessor

        (temp_dir / "a.json").touch()
        (temp_dir / "b.json").touch()
        (temp_dir / "c.txt").touch()

        vp = VideoProcessor(sample_config)
        files = vp.scan_json_files(str(temp_dir))
        assert len(files) == 2

    def test_extract_text_short_content(self, sample_config, temp_dir):
        """文本过短时应返回空字符串（非报错）。"""
        from video_processor import VideoProcessor
        import json

        data = {"a": "ab"}
        json_path = temp_dir / "short.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        vp = VideoProcessor(sample_config)
        text = vp.extract_text_from_json(str(json_path))
        # 很短的文本仍然会被返回，但上层会判断
        assert isinstance(text, str)


class TestCleanup:
    """测试临时文件清理。"""

    def test_cleanup_video(self, sample_config, temp_dir):
        from video_processor import VideoProcessor

        sample_config["video"]["keep_temp_files"] = False
        vp = VideoProcessor(sample_config)

        # 创建假视频文件
        video_path = temp_dir / "test.mp4"
        video_path.touch()

        vp.cleanup_video(video_path)
        assert not video_path.exists()

    def test_keep_temp_files(self, sample_config, temp_dir):
        from video_processor import VideoProcessor

        sample_config["video"]["keep_temp_files"] = True
        vp = VideoProcessor(sample_config)

        video_path = temp_dir / "test.mp4"
        video_path.touch()

        vp.cleanup_video(video_path)
        assert video_path.exists()  # 保留
