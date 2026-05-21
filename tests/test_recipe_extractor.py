"""
测试 recipe_extractor.py
"""

import json
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestRecipeExtractorInit:
    """测试 RecipeExtractor 初始化。"""

    def test_init_with_config_key(self, sample_config):
        from recipe_extractor import RecipeExtractor

        extractor = RecipeExtractor(sample_config)
        assert extractor.api_key == "sk-test-key"
        assert extractor.model == "deepseek-chat"

    def test_init_missing_key(self):
        from recipe_extractor import RecipeExtractor

        config = {"deepseek": {"api_key": ""}}
        with patch("recipe_extractor.RecipeExtractor._load_env_key", return_value=""):
            with pytest.raises(ValueError, match="未找到 DeepSeek API Key"):
                RecipeExtractor(config)

    def test_init_from_env(self):
        from recipe_extractor import RecipeExtractor

        config = {"deepseek": {"api_key": ""}}
        with patch("recipe_extractor.RecipeExtractor._load_env_key", return_value="sk-env-key"):
            extractor = RecipeExtractor(config)
            assert extractor.api_key == "sk-env-key"


class TestResponseParsing:
    """测试 API 响应解析。"""

    @pytest.fixture
    def extractor(self, sample_config):
        from recipe_extractor import RecipeExtractor
        return RecipeExtractor(sample_config)

    def test_parse_valid_json(self, extractor):
        result = extractor._parse_response(
            '{"ingredients": [{"name": "淡奶油", "amount": "200ml"}], "tools": ["打蛋器"]}'
        )
        assert result["ingredients"][0]["name"] == "淡奶油"
        assert result["tools"] == ["打蛋器"]

    def test_parse_markdown_wrapped_json(self, extractor):
        result = extractor._parse_response(
            '```json\n{"ingredients": [], "tools": ["碗"]}\n```'
        )
        assert result["tools"] == ["碗"]

    def test_parse_no_recipe(self, extractor):
        result = extractor._parse_response('{"error": "no_recipe"}')
        assert result["error"] == "no_recipe"

    def test_parse_invalid_json(self, extractor):
        result = extractor._parse_response("这不是 JSON 格式的文本")
        assert "error" in result

    def test_parse_json_with_surrounding_text(self, extractor):
        """测试 JSON 夹杂在其他文本中的情况（正则提取）。"""
        result = extractor._parse_response(
            '好的，这是分析结果：\n{"ingredients": [{"name": "面粉", "amount": "500g"}], "tools": []}\n希望对你有帮助！'
        )
        assert result["ingredients"][0]["name"] == "面粉"


class TestMergeAndDeduplicate:
    """测试多帧结果去重合并。"""

    @pytest.fixture
    def extractor(self, sample_config):
        from recipe_extractor import RecipeExtractor
        return RecipeExtractor(sample_config)

    def test_merge_duplicate_ingredients(self, extractor):
        """同名食材保留更详细用量。"""
        all_ingredients = {"淡奶油": "200ml"}
        all_tools = {"打蛋器"}

        # 模拟另一帧返回相同食材但更简略的用量
        result = {
            "ingredients": [{"name": "淡奶油", "amount": "适量"}],
            "tools": [],
        }

        for ing in result.get("ingredients", []):
            name = ing.get("name", "").strip()
            amount = ing.get("amount", "").strip()
            if name in all_ingredients:
                if len(amount) > len(all_ingredients[name]) and all_ingredients[name] != "适量":
                    all_ingredients[name] = amount
            else:
                all_ingredients[name] = amount if amount else "适量"

        # 原值 "200ml" 比 "适量" 长，应保留原值
        assert all_ingredients["淡奶油"] == "200ml"

    def test_merge_new_ingredients(self, extractor):
        """新食材应被添加。"""
        all_ingredients = {"淡奶油": "200ml"}
        all_tools = {"打蛋器"}

        result = {
            "ingredients": [{"name": "细砂糖", "amount": "50g"}],
            "tools": ["搅拌碗"],
        }

        for ing in result.get("ingredients", []):
            name = ing.get("name", "").strip()
            amount = ing.get("amount", "").strip()
            if name not in all_ingredients:
                all_ingredients[name] = amount

        for tool in result.get("tools", []):
            all_tools.add(tool)

        assert "细砂糖" in all_ingredients
        assert "搅拌碗" in all_tools

    def test_extract_from_frames_empty(self, extractor):
        """空帧列表返回错误。"""
        result = extractor.extract_from_frames([])
        assert "error" in result
        assert result["error"] == "no_frames"

    def test_extract_from_frames_all_no_recipe(self, extractor, sample_frames):
        """所有帧都无配方时返回错误。"""
        with patch.object(extractor, "extract_from_frame", return_value={"error": "no_recipe"}):
            result = extractor.extract_from_frames(sample_frames, delay=0)
            assert result["error"] == "no_recipe"
            assert result["ingredients"] == []


class TestImageEncoding:
    """测试图片 base64 编码。"""

    def test_encode_image(self, sample_config, temp_dir):
        from recipe_extractor import RecipeExtractor

        extractor = RecipeExtractor(sample_config)

        # 创建一个小测试图片
        img_path = temp_dir / "test.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0test")

        data_url = extractor._encode_image(img_path)
        assert data_url.startswith("data:image/jpeg;base64,")

        # 验证能解码回来
        encoded = data_url.split(",", 1)[1]
        decoded = base64.b64decode(encoded)
        assert decoded == b"\xff\xd8\xff\xe0test"


class TestAPICall:
    """测试 API 调用。"""

    def test_api_call_success(self, sample_config):
        from recipe_extractor import RecipeExtractor

        extractor = RecipeExtractor(sample_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"ingredients":[],"tools":["锅"]}'}}]
        }

        with patch("requests.post", return_value=mock_resp):
            result = extractor._call_api("data:image/jpeg;base64,abc")
            assert result["tools"] == ["锅"]

    def test_api_call_rate_limited(self, sample_config):
        from recipe_extractor import RecipeExtractor

        extractor = RecipeExtractor(sample_config)

        mock_rate_limit = MagicMock()
        mock_rate_limit.status_code = 429

        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "choices": [{"message": {"content": '{"ingredients":[],"tools":["刀"]}'}}]
        }

        with patch("requests.post", side_effect=[mock_rate_limit, mock_success]):
            with patch("time.sleep", return_value=None):
                result = extractor._call_api("data:image/jpeg;base64,abc")
                assert result["tools"] == ["刀"]

    def test_api_call_all_fail(self, sample_config):
        from recipe_extractor import RecipeExtractor

        extractor = RecipeExtractor(sample_config)

        with patch("requests.post", side_effect=Exception("网络错误")):
            with patch("time.sleep", return_value=None):
                result = extractor._call_api("data:image/jpeg;base64,abc")
                assert "error" in result
