"""
测试 main.py（命令行入口）。
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestNormalizeURL:
    """测试 URL 标准化。"""

    def test_full_url_unchanged(self):
        from main import normalize_url

        url = "https://www.bilibili.com/video/BV1ML4y1W7Bd"
        assert normalize_url(url) == url

    def test_bv_number(self):
        from main import normalize_url

        assert normalize_url("BV1ML4y1W7Bd") == \
            "https://www.bilibili.com/video/BV1ML4y1W7Bd"

    def test_b23_short_link(self):
        from main import normalize_url

        result = normalize_url("b23.tv/abc123")
        assert result.startswith("https://")
        assert "b23.tv" in result

    def test_strip_whitespace(self):
        from main import normalize_url

        result = normalize_url("  BV1xxx  ")
        assert result == "https://www.bilibili.com/video/BV1xxx"


class TestLoadConfig:
    """测试配置加载。"""

    def test_load_existing_config(self, config_file):
        from main import load_config

        config = load_config(str(config_file))
        assert "deepseek" in config
        assert config["deepseek"]["model"] == "deepseek-chat"

    def test_load_missing_config(self, temp_dir):
        from main import load_config

        config = load_config(str(temp_dir / "nonexistent.yaml"))
        assert config == {}  # 返回空字典


class TestParseArgs:
    """测试命令行参数解析。"""

    def test_required_url(self):
        from main import parse_args

        with patch.object(sys, "argv", ["main.py", "--url", "BV1xxx"]):
            args = parse_args()
            assert args.url == "BV1xxx"

    def test_all_flags(self):
        from main import parse_args

        test_args = [
            "main.py",
            "--url", "BV1xxx",
            "--config", "my_config.yaml",
            "--keep-temp",
            "--interval", "3",
            "--verbose",
            "--port", "8080",
        ]
        with patch.object(sys, "argv", test_args):
            args = parse_args()
            assert args.url == "BV1xxx"
            assert args.config == "my_config.yaml"
            assert args.keep_temp is True
            assert args.interval == 3
            assert args.verbose is True
            assert args.port == 8080

    def test_missing_all_args_returns_none_url(self):
        """--url 不再是 required，无参数时 url 为 None。"""
        from main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()
            assert args.url is None
            assert args.json is None
            assert args.scan_json is False

    def test_json_mode(self):
        """测试 --json 参数。"""
        from main import parse_args

        with patch.object(sys, "argv", ["main.py", "--json", "data.json"]):
            args = parse_args()
            assert args.json == "data.json"

    def test_scan_json_mode(self):
        """测试 --scan-json 参数。"""
        from main import parse_args

        with patch.object(sys, "argv", ["main.py", "--scan-json"]):
            args = parse_args()
            assert args.scan_json is True


class TestMainFlow:
    """测试主流程。"""

    def test_main_no_frames_exits(self, sample_config, temp_dir):
        """未能筛选到帧时优雅退出。"""
        from main import main

        sample_config["video"]["frames_dir"] = str(temp_dir)
        sample_config["video"]["download_dir"] = str(temp_dir)

        test_args = [
            "main.py",
            "--url", "BV1xxx",
            "--config", str(temp_dir / "test_config.yaml"),
        ]

        import yaml
        config_path = temp_dir / "test_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f)

        with patch.object(sys, "argv", test_args):
            with patch("video_processor.VideoProcessor.process", return_value=[]):
                with patch("video_processor.VideoProcessor.cleanup_all"):
                    with pytest.raises(SystemExit) as exc:
                        main()
                    assert exc.value.code == 1

    def test_main_no_recipe_exits(self, sample_config, temp_dir):
        """未提取到配方时优雅退出（网页版分析器返回 error）。"""
        from main import main

        sample_config["video"]["frames_dir"] = str(temp_dir)
        sample_config["video"]["download_dir"] = str(temp_dir)

        test_args = [
            "main.py",
            "--url", "BV1xxx",
            "--config", str(temp_dir / "test_config.yaml"),
        ]

        import yaml
        config_path = temp_dir / "test_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f)

        fake_frames = [temp_dir / "f.jpg"]
        for fp in fake_frames:
            fp.touch()

        with patch.object(sys, "argv", test_args):
            with patch("video_processor.VideoProcessor.process", return_value=fake_frames):
                with patch("video_processor.VideoProcessor.cleanup_all"):
                    with patch("video_processor.VideoProcessor.cleanup_frames"):
                        with patch("deepseek_web_analyzer.analyze_frames_with_deepseek_web",
                                   return_value={"error": "no_recipe", "message": "test"}):
                            with pytest.raises(SystemExit) as exc:
                                main()
                            assert exc.value.code == 1

    def test_main_no_api_key_still_works_with_web_analyzer(self, sample_config, temp_dir):
        """视频管线使用网页版分析器，不依赖 API Key —— 空 key 也能跑通。"""
        from main import main

        sample_config["deepseek"]["api_key"] = ""
        sample_config["video"]["frames_dir"] = str(temp_dir)
        sample_config["video"]["download_dir"] = str(temp_dir)

        test_args = [
            "main.py",
            "--url", "BV1xxx",
            "--config", str(temp_dir / "test_config.yaml"),
        ]

        import yaml
        config_path = temp_dir / "test_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f)

        fake_frames = [temp_dir / "f.jpg"]
        for fp in fake_frames:
            fp.touch()

        with patch.object(sys, "argv", test_args):
            with patch("video_processor.VideoProcessor.process", return_value=fake_frames):
                with patch("video_processor.VideoProcessor.cleanup_all"):
                    with patch("video_processor.VideoProcessor.cleanup_frames"):
                        with patch("deepseek_web_analyzer.analyze_frames_with_deepseek_web",
                                   return_value={"ingredients": [{"name": "蛋", "amount": "2个"}],
                                                 "tools": ["碗"]}):
                            with patch("main.start_web_server") as mock_web:
                                main()
                                mock_web.assert_called_once()
