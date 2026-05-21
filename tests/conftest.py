"""
pytest 共享 fixtures 和配置。
"""

import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理。"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_config():
    """生成测试用配置。"""
    return {
        "deepseek": {
            "api_key": "sk-test-key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "max_tokens": 2000,
            "temperature": 0.1,
        },
        "video": {
            "download_dir": "./temp/videos",
            "frames_dir": "./temp/frames",
            "frame_interval": 5,
            "use_scene_detection": False,
            "max_frames": 10,
            "keep_temp_files": False,
        },
        "ocr": {
            "min_chinese_chars": 50,
            "languages": ["ch_sim", "en"],
        },
        "web": {
            "host": "127.0.0.1",
            "port": 5000,
            "auto_open_browser": False,
        },
    }


@pytest.fixture
def sample_recipe():
    """生成测试用配方数据。"""
    return {
        "ingredients": [
            {"name": "淡奶油", "amount": "200ml"},
            {"name": "细砂糖", "amount": "50g"},
            {"name": "吉利丁片", "amount": "10g"},
        ],
        "tools": ["打蛋器", "雪糕模具", "搅拌碗"],
    }


@pytest.fixture
def sample_frames(temp_dir):
    """生成测试用帧图片路径列表。"""
    frames = []
    for i in range(3):
        fp = temp_dir / f"frame_{i:04d}.jpg"
        fp.touch()
        frames.append(fp)
    return frames


@pytest.fixture
def config_file(temp_dir, sample_config):
    """生成测试用 config.yaml。"""
    config_path = temp_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config, f)
    return config_path
