"""
测试 web_interface.py
"""

import json
import re

import pytest


class TestBuildPageHTML:
    """测试 HTML 页面生成。"""

    def test_generates_valid_html(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_ingredients_injected(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )

        # 检查 JSON 数据被注入
        assert "淡奶油" in html
        assert "200ml" in html
        assert "打蛋器" in html

    def test_empty_data(self):
        from web_interface import build_page_html

        html = build_page_html([], [])
        assert "[]" in html  # 空 JSON 数组
        assert "<!DOCTYPE html>" in html

    def test_special_characters_escaped(self):
        from web_interface import build_page_html

        ingredients = [{"name": '测试"引号', "amount": "1个"}]
        html = build_page_html(ingredients, [])

        # JSON 编码应正确处理引号
        assert '测试"引号' in html or '测试\\"引号' in html

    def test_integrity_of_injected_json(self, sample_recipe):
        """注入的 JSON 应该是合法的 JavaScript。"""
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )

        # 提取注入的 JSON（在 <script> 中）
        match = re.search(r'const INGREDIENTS = (\[.*?\]);', html, re.DOTALL)
        assert match is not None
        parsed = json.loads(match.group(1))
        assert parsed[0]["name"] == "淡奶油"


class TestWebServerInit:
    """测试 Web 服务器初始化。"""

    def test_init_with_config(self, sample_config):
        from web_interface import WebServer

        server = WebServer(sample_config)
        assert server.host == "127.0.0.1"
        assert server.port == 5000
        assert server.auto_open is False  # 测试中关闭

    def test_set_recipe_data(self, sample_config, sample_recipe):
        from web_interface import WebServer

        server = WebServer(sample_config)
        server.set_recipe_data(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert len(server.ingredients) == 3
        assert len(server.tools) == 3
        assert server.ingredients[0]["name"] == "淡奶油"


class TestFlaskRoutes:
    """测试 Flask 路由。"""

    @pytest.fixture
    def client(self, sample_config, sample_recipe):
        from web_interface import WebServer

        server = WebServer(sample_config)
        server.set_recipe_data(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        return server.app.test_client()

    def test_index_route(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "淡奶油" in resp.data.decode("utf-8")

    def test_api_recipe_route(self, client):
        resp = client.get("/api/recipe")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["ingredients"]) == 3
        assert "打蛋器" in data["tools"]


class TestHTMLFeatures:
    """测试 HTML 页面的关键功能标记。"""

    def test_has_checkboxes(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert 'type="checkbox"' in html

    def test_has_generate_button(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert "生成购物车" in html

    def test_has_jd_search_function(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert "search.jd.com" in html
        assert "jdSearchUrl" in html

    def test_has_select_all(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert "toggleAll" in html
        assert "全选" in html

    def test_has_open_all_button(self, sample_recipe):
        from web_interface import build_page_html

        html = build_page_html(
            sample_recipe["ingredients"], sample_recipe["tools"]
        )
        assert "一键打开所有链接" in html
