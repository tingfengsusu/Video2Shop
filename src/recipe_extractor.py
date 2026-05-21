"""
配方提取模块：调用 DeepSeek 视觉 API 从图片中提取食材和工具清单。
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests

logger = logging.getLogger(__name__)

# DeepSeek API 提示词（图片输入）
EXTRACT_PROMPT = """你是一个专业的食谱分析助手。请分析这张图片，提取出制作菜品所需的所有：

1. 食材清单（每项包含名称和用量，如果用量没有明确说明，amount 填写 "适量"）
2. 工具清单

输出格式必须是严格的 JSON，例如：
{"ingredients": [{"name": "淡奶油", "amount": "200ml"}], "tools": ["打蛋器", "雪糕模具"]}

如果图片中没有配方信息，返回：
{"error": "no_recipe"}

只输出 JSON，不要输出任何其他内容。"""

# DeepSeek API 提示词（纯文本输入 — JSON 回退模式）
EXTRACT_TEXT_PROMPT = """你是一个专业的食谱分析助手。下面是从B站视频的评论、弹幕、简介中提取的文本内容。

请从中提取出制作菜品/甜点所需的所有：

1. 食材清单（每项包含名称和用量，如果用量没有明确说明，amount 填写 "适量"）
2. 工具清单

注意：
- 文本中可能包含网友讨论、闲聊等无关内容，请只提取与配方相关的信息
- 同样的食材可能有不同叫法，请合并去重
- 用量单位可能是 g, ml, 克, 毫升, 勺, 杯等，请保留原文单位

输出格式必须是严格的 JSON，例如：
{"ingredients": [{"name": "淡奶油", "amount": "200ml"}], "tools": ["打蛋器", "雪糕模具"]}

如果文本中没有配方信息，返回：
{"error": "no_recipe"}

只输出 JSON，不要输出任何其他内容。"""


class RecipeExtractor:
    """调用 DeepSeek API 从图片提取配方。"""

    def __init__(self, config: dict):
        ds_cfg = config.get("deepseek", {})

        # API Key 优先级：配置文件 > 环境变量
        self.api_key = ds_cfg.get("api_key", "") or self._load_env_key()
        if not self.api_key:
            raise ValueError(
                "未找到 DeepSeek API Key。请在 config.yaml 中设置 deepseek.api_key，"
                "或设置环境变量 DEEPSEEK_API_KEY。\n"
                "获取方式：访问 https://platform.deepseek.com 注册并创建 API Key。"
            )

        self.base_url = ds_cfg.get("base_url", "https://api.deepseek.com")
        self.model = ds_cfg.get("model", "deepseek-chat")
        self.max_tokens = ds_cfg.get("max_tokens", 2000)
        self.temperature = ds_cfg.get("temperature", 0.1)

    @staticmethod
    def _load_env_key() -> str:
        """从 .env 文件和环境变量加载 API Key。"""
        try:
            from dotenv import load_dotenv
            import os

            load_dotenv()
            return os.getenv("DEEPSEEK_API_KEY", "")
        except ImportError:
            import os

            return os.getenv("DEEPSEEK_API_KEY", "")

    def _encode_image(self, image_path: Path) -> str:
        """将图片编码为 base64 data URL。"""
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        # 检测图片格式
        suffix = image_path.suffix.lower()
        mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}
        mime = mime_map.get(suffix, "jpeg")

        return f"data:image/{mime};base64,{img_data}"

    def _call_api(self, base64_image: str) -> Dict[str, Any]:
        """调用 DeepSeek API，返回解析后的 JSON 结果。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": EXTRACT_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": base64_image},
                        },
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 30)
                    logger.warning(f"API 限流，等待 {wait} 秒后重试...")
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.error(f"API 返回错误 ({resp.status_code}): {resp.text[:500]}")
                    # 如果是模型不支持多模态，给出明确提示
                    if "model" in resp.text.lower() or "multimodal" in resp.text.lower():
                        logger.error(
                            "当前模型可能不支持图片输入。"
                            "请确认 DeepSeek 视觉 API 是否可用，或尝试使用网页版。"
                        )
                    return self._parse_response(resp.text)

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_response(content)

            except requests.exceptions.Timeout:
                logger.warning(f"API 请求超时 (第 {attempt + 1}/{max_retries} 次)")
                if attempt < max_retries - 1:
                    time.sleep(3)

            except requests.exceptions.ConnectionError:
                logger.warning(f"网络连接失败 (第 {attempt + 1}/{max_retries} 次)")
                if attempt < max_retries - 1:
                    time.sleep(5)

            except Exception as e:
                logger.error(f"API 调用异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)

        return {"error": "api_failed", "message": "多次尝试后 API 调用仍然失败"}

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """从 API 响应中提取 JSON。"""
        content = content.strip()

        # 移除可能的 markdown 代码块标记
        if content.startswith("```"):
            lines = content.split("\n")
            # 移除首行 ```json 和末行 ```
            content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[: content.rfind("```")].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试用正则提取 JSON 对象
            import re

            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            logger.error(f"无法解析 API 返回的 JSON: {content[:300]}")
            return {"error": "parse_failed", "raw": content[:500]}

    def _call_text_api(self, text: str) -> Dict[str, Any]:
        """调用 DeepSeek API（纯文本模式），返回解析后的 JSON 结果。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": f"{EXTRACT_TEXT_PROMPT}\n\n文本内容：\n{text[:8000]}"
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 30)
                    logger.warning(f"API 限流，等待 {wait} 秒后重试...")
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.error(f"API 返回错误 ({resp.status_code}): {resp.text[:500]}")
                    return self._parse_response(resp.text)

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_response(content)

            except requests.exceptions.Timeout:
                logger.warning(f"API 请求超时 (第 {attempt + 1}/{max_retries} 次)")
                if attempt < max_retries - 1:
                    time.sleep(3)
            except requests.exceptions.ConnectionError:
                logger.warning(f"网络连接失败 (第 {attempt + 1}/{max_retries} 次)")
                if attempt < max_retries - 1:
                    time.sleep(5)
            except Exception as e:
                logger.error(f"API 调用异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)

        return {"error": "api_failed", "message": "多次尝试后 API 调用仍然失败"}

    def extract_from_text(self, text: str) -> Dict[str, Any]:
        """从纯文本中提取配方（JSON回退模式，无需图片/视觉API）。
        返回: {"ingredients": [...], "tools": [...]} 或 {"error": "..."}
        """
        logger.info(f"从文本提取配方 (共 {len(text)} 字符)...")
        result = self._call_text_api(text)

        if "error" in result:
            logger.warning(f"文本提取失败: {result.get('error', 'unknown')}")
        else:
            n_ingr = len(result.get("ingredients", []))
            n_tools = len(result.get("tools", []))
            logger.info(f"文本提取: {n_ingr} 种食材, {n_tools} 个工具")

        return result

    def extract_from_frame(self, image_path: Path) -> Dict[str, Any]:
        """从单张图片提取配方。"""
        logger.info(f"正在分析图片: {image_path.name}")
        base64_img = self._encode_image(image_path)
        result = self._call_api(base64_img)

        if "error" in result:
            logger.warning(f"  {image_path.name}: {result.get('error', 'unknown')}")
        else:
            n_ingr = len(result.get("ingredients", []))
            n_tools = len(result.get("tools", []))
            logger.info(f"  {image_path.name}: 提取到 {n_ingr} 种食材, {n_tools} 个工具")

        return result

    def extract_from_frames(
        self, frame_paths: List[Path], delay: float = 1.0
    ) -> Dict[str, Any]:
        """从多帧图片提取配方，合并去重。"""
        if not frame_paths:
            return {"ingredients": [], "tools": [], "error": "no_frames"}

        all_ingredients: Dict[str, str] = {}  # name -> amount
        all_tools: set = set()

        any_success = False

        for i, fp in enumerate(frame_paths):
            if i > 0:
                time.sleep(delay)  # 避免 API 限流

            result = self.extract_from_frame(fp)

            if "error" in result:
                continue

            any_success = True

            # 合并食材（同名取更详细的用量）
            for ing in result.get("ingredients", []):
                name = ing.get("name", "").strip()
                amount = ing.get("amount", "").strip()
                if not name:
                    continue
                # 保留更详细的用量信息
                if name in all_ingredients:
                    old_amount = all_ingredients[name]
                    if len(amount) > len(old_amount) and old_amount != "适量":
                        all_ingredients[name] = amount
                else:
                    all_ingredients[name] = amount if amount else "适量"

            # 合并工具
            for tool in result.get("tools", []):
                tool_name = tool.strip() if isinstance(tool, str) else str(tool).strip()
                if tool_name:
                    all_tools.add(tool_name)

        if not any_success:
            return {
                "ingredients": [],
                "tools": [],
                "error": "no_recipe",
                "message": "所有图片均未检测到配方信息，请更换视频或检查 API 配置。",
            }

        ingredients_list = [
            {"name": name, "amount": amount}
            for name, amount in all_ingredients.items()
        ]

        return {
            "ingredients": ingredients_list,
            "tools": sorted(all_tools),
        }
