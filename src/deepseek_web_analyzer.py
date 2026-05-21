"""
DeepSeek 网页版分析器 — 通过 Playwright 浏览器自动化上传图片并提取配方 JSON。

工作原理:
  1. 启动 Chromium → 打开 https://chat.deepseek.com/
  2. 首次运行时弹出浏览器窗口，等用户手动登录（扫码/手机号）
  3. 登录后保存 cookies → deepseek_auth.json，后续自动复用
  4. 一次性上传多张图片，等待全部加载完成后自动发送提示词
  5. 从回复的 markdown 区域提取 JSON，解析后返回配方 dict

依赖: pip install playwright && playwright install chromium
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 发送给 DeepSeek 网页版的提示词
ANALYSIS_PROMPT = (
    "从给定的B站视频图片中，提取一份精确的制作配方。\n\n"
    "限制：\n"
    "- 配方必须完全基于图片里UP主实际演示时提及的食材、用量和步骤。\n"
    "- 禁止自行编造或从其他地方补充视频中没有的配方内容。\n"
    "- 如有信息不明确或缺失，请如实告知。\n\n"
    "输出格式：以清晰的JSON格式输出，包含 \"ingredients\"（食材清单）和 \"tools\"（工具清单）两个字段。\n"
    '示例：{"ingredients": [{"name": "淡奶油", "amount": "200ml"}], "tools": ["打蛋器", "雪糕模具"]}\n\n'
    "只输出 JSON，不要输出任何其他内容。"
)

# 每批最多上传的图片数（DeepSeek 网页版限制）

class DeepSeekWebAnalyzer:
    """通过浏览器自动化与 DeepSeek 网页版交互，上传图片并提取配方。"""

    def __init__(self, config: dict):
        ds_web = config.get("deepseek_web", {})
        self.headless = ds_web.get("headless", False)
        self.timeout = ds_web.get("timeout_seconds", 120) * 1000  # 转为毫秒
        self.cookies_file = Path(ds_web.get("cookies_file", "config/deepseek_auth.json"))
        self.batch_size = ds_web.get("batch_size", 5)
        self.browser = None
        self.context = None
        self.page = None

    # ── 浏览器生命周期 ──────────────────────────────────────────────────

    def _launch_chrome(self, launch_args: dict):
        """启动系统 Chrome，降级策略：channel → executable_path → 报错。"""
        # 策略 1：channel="chrome" 让 Playwright 自动寻找系统 Chrome
        try:
            logger.info("  尝试 channel='chrome' ...")
            return self._pw.chromium.launch(channel="chrome", **launch_args)
        except Exception as e1:
            logger.warning(f"  channel='chrome' 失败: {e1}")

        # 策略 2：常见安装路径
        import platform

        if platform.system() == "Windows":
            candidate_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
                    __import__("os").environ.get("USERNAME", "")
                ),
            ]
        elif platform.system() == "Darwin":
            candidate_paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        else:
            candidate_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/snap/bin/chromium",
            ]

        for path in candidate_paths:
            if __import__("pathlib").Path(path).exists():
                try:
                    logger.info(f"  尝试 executable_path='{path}' ...")
                    return self._pw.chromium.launch(
                        executable_path=path, **launch_args
                    )
                except Exception as e2:
                    logger.warning(f"  executable_path='{path}' 失败: {e2}")

        raise RuntimeError(
            "无法启动 Chrome 浏览器。请确认：\n"
            "  1. 系统已安装 Google Chrome\n"
            "  2. 或运行: playwright install chromium\n"
            f"  已尝试的路径: {candidate_paths}"
        )

    def _ensure_browser(self):
        """启动 Playwright + 系统 Chrome，加载已保存的登录态。"""
        if self.browser is not None:
            return

        from playwright.sync_api import sync_playwright

        logger.info("启动系统 Chrome 浏览器...")
        self._pw = sync_playwright().start()

        launch_args = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }

        self.browser = self._launch_chrome(launch_args)

        # 如果有已保存的 cookies，恢复登录态
        if self.cookies_file.exists():
            logger.info(f"加载已保存的登录态: {self.cookies_file}")
            self.context = self.browser.new_context(
                storage_state=str(self.cookies_file)
            )
        else:
            self.context = self.browser.new_context()

        self.page = self.context.new_page()
        # 隐藏自动化特征
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    def _close(self):
        """关闭浏览器。"""
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if hasattr(self, "_pw"):
            try:
                self._pw.stop()
            except Exception:
                pass
        self.browser = None
        self.context = None
        self.page = None

    # ── 登录处理 ────────────────────────────────────────────────────────

    def _ensure_logged_in(self):
        """确保已登录 DeepSeek。首次运行会等待用户手动登录。"""
        self._ensure_browser()
        self.page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded")

        # 判断是否需要登录：检查页面上是否有聊天输入框
        try:
            self.page.wait_for_selector(
                'textarea, [contenteditable="true"], [role="textbox"]',
                timeout=8000,
            )
            logger.info("已在登录态，跳过登录流程")
            return
        except Exception:
            pass

        # 需要登录 — 等待用户手动操作
        logger.info("=" * 50)
        logger.info("⚠ 请在打开的浏览器窗口中完成 DeepSeek 登录（扫码或手机号）。")
        logger.info("  登录成功后，程序将自动继续...")
        logger.info("=" * 50)

        try:
            self.page.wait_for_selector(
                'textarea, [contenteditable="true"], [role="textbox"]',
                timeout=300000,  # 5 分钟
            )
            logger.info("登录成功！")

            self.context.storage_state(path=str(self.cookies_file))
            logger.info(f"登录态已保存到: {self.cookies_file}")

        except Exception:
            raise RuntimeError(
                "登录超时（5 分钟）。请确认：\n"
                "  1. 浏览器窗口已打开 https://chat.deepseek.com/\n"
                "  2. 已完成扫码或手机号登录\n"
                "  3. 网络可正常访问 DeepSeek"
            )

    # ── 多图上传 + 等待加载 ─────────────────────────────────────────────

    def _upload_images_batch(self, image_paths: List[Path]):
        """一次性上传多张图片到 DeepSeek 聊天输入框。

        参数:
            image_paths: 图片路径列表（建议不超过 5 张）
        """
        path_strs = [str(fp.resolve()) for fp in image_paths]
        logger.info(f"  批量上传 {len(path_strs)} 张图片...")

        # 策略 1: 查找隐藏的 <input type="file"> 并直接赋值（支持多文件）
        file_inputs = self.page.locator('input[type="file"]')
        count = file_inputs.count()
        if count > 0:
            # 找到支持多文件上传的 input
            for i in range(count):
                inp = file_inputs.nth(i)
                try:
                    multiple_attr = inp.get_attribute("multiple")
                    # multiple 属性存在（即使是空字符串）表示支持多文件
                    if multiple_attr is not None:
                        inp.set_input_files(path_strs)
                        logger.info(f"  已通过 input[type=file][multiple] 上传 {len(path_strs)} 张图片")
                        return
                except Exception:
                    continue
            # 没有 multiple 属性，尝试第一个 input
            try:
                file_inputs.first.set_input_files(path_strs)
                logger.info(f"  已通过 input[type=file] 上传 {len(path_strs)} 张图片")
                return
            except Exception as e:
                logger.warning(f"  input[type=file] 上传失败: {e}")

        # 策略 2: 点击上传按钮触发文件选择对话框
        upload_selectors = [
            '[aria-label*="upload" i]',
            '[aria-label*="上传" i]',
            '[title*="upload" i]',
            'button:has(svg)',
            '[data-testid="file-upload"]',
        ]
        for sel in upload_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    with self.page.expect_file_chooser(timeout=5000) as fc_info:
                        btn.click()
                    file_chooser = fc_info.value
                    file_chooser.set_files(path_strs)
                    logger.info(f"  已通过 file chooser 上传 {len(path_strs)} 张图片")
                    return
            except Exception:
                continue

        raise RuntimeError(
            f"无法上传图片。请确认 DeepSeek 网页版支持图片上传功能。"
        )

    def _wait_for_images_loaded(self, expected_count: int, timeout_ms: int = 30000):
        """等待所有上传的图片加载完成，发送按钮变为可点击状态。

        DeepSeek 发送按钮是 <div role="button" aria-disabled="...">。
        图片未加载完时 aria-disabled="true"，加载完成后变为 "false"。

        选择策略：取页面上最后一个 div[role="button"][aria-disabled]，
        因为发送按钮通常位于输入区域末端。
        """
        logger.info(f"  等待 {expected_count} 张图片加载完成（超时 {timeout_ms // 1000}s）...")

        try:
            self.page.wait_for_function(
                """() => {
                    const all = document.querySelectorAll('div[role="button"][aria-disabled]');
                    if (all.length === 0) return false;
                    // 取最后一个带 aria-disabled 的 div[role="button"]
                    const btn = all[all.length - 1];
                    return btn.getAttribute('aria-disabled') === 'false'
                        && btn.offsetParent !== null;
                }""",
                timeout=timeout_ms,
            )
            logger.info("  图片加载完成，发送按钮已可点击")
        except Exception:
            logger.warning(f"  等待超时（{timeout_ms // 1000}s），尝试继续")

    def _wait_for_send_disabled(self, timeout_ms: int = 10000):
        """点击发送后，等待发送按钮 aria-disabled 变为 'true'（表示正在分析中）。"""
        try:
            self.page.wait_for_function(
                """() => {
                    const all = document.querySelectorAll('div[role="button"][aria-disabled]');
                    if (all.length === 0) return false;
                    const btn = all[all.length - 1];
                    return btn.getAttribute('aria-disabled') === 'true';
                }""",
                timeout=timeout_ms,
            )
            logger.info("  已进入分析状态 (aria-disabled=true)")
        except Exception:
            logger.warning("  等待分析状态超时，继续等待回复")

    # ── 发送提示词 ──────────────────────────────────────────────────────

    def _send_prompt(self, prompt: str):
        """填入提示词并点击发送按钮。

        DeepSeek 输入框按 Enter 不会发送，必须点击发送按钮。
        发送按钮实际为 <div role="button" aria-disabled="...">，不含 aria-label。
        定位逻辑见 _find_and_click_send_button。
        """
        logger.info("  填入提示词...")

        # 找到输入框
        input_selectors = [
            'textarea',
            '[contenteditable="true"]',
            '[role="textbox"]',
            '#chat-input',
        ]
        input_box = None
        for sel in input_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if input_box is None:
            raise RuntimeError("未找到 DeepSeek 聊天输入框")

        # 填入文本
        input_box.click()
        time.sleep(0.3)
        input_box.fill(prompt)
        time.sleep(0.5)

        # 精确定位并点击发送按钮（不使用 Enter 降级）
        send_btn = self._find_and_click_send_button()
        if not send_btn:
            raise RuntimeError(
                "无法找到或点击发送按钮。请确认：\n"
                "  1. DeepSeek 页面已完全加载\n"
                "  2. 图片已上传完成（aria-disabled=false）\n"
                "  3. 页面没有弹窗遮挡"
            )


    def _find_and_click_send_button(self) -> bool:
        """精确定位 DeepSeek 发送按钮并点击。

        DeepSeek 发送按钮实际是 <div role="button" aria-disabled="...">，
        不是 <button> 标签，也没有 aria-label 属性。

        按优先级尝试:
          1. div[role="button"]:has(svg) — 带 SVG 图标的功能按钮（选最后一个，即发送）
          2. div[role="button"][aria-disabled="false"] — 匹配可点击的 div 按钮
          3. button[aria-label="发送"] — 旧版 DeepSeek 兼容
          4. button:has-text("发送") — 文字按钮降级
        """
        # ── 策略 1: 优先匹配 div[role="button"] 类型的发送按钮 ──────────
        div_selectors = [
            # 精确：通过发送图标的 SVG path 特征匹配
            'div[role="button"]:has(svg path[d*="M8.3125 0.981587"])',
            # 通用：所有带 aria-disabled 的 div 按钮，取最后一个
            'div[role="button"][aria-disabled="false"]',
            # 回退：所有带 SVG 的 div 按钮，尝试找末尾那个
            'div[role="button"]:has(svg)',
        ]

        for sel in div_selectors:
            try:
                loc = self.page.locator(sel)
                count = loc.count()
                if count == 0:
                    continue

                # 有多个匹配时，发送按钮通常是最后一个
                for idx in range(count - 1, -1, -1):
                    btn = loc.nth(idx)
                    try:
                        btn.wait_for(state="visible", timeout=2000)
                    except Exception:
                        continue

                    aria_disabled = btn.get_attribute("aria-disabled")
                    # 必须 aria-disabled 不是 "true"
                    if aria_disabled == "true":
                        continue
                    # 没有 aria-disabled 属性的跳过（可能是其他按钮）
                    if aria_disabled is None:
                        continue

                    logger.info(f"  点击 div 类型发送按钮: {sel} (第 {idx + 1}/{count} 个)")
                    btn.click(timeout=5000)
                    logger.info("  提示词已发送")
                    return True

            except Exception as e:
                logger.debug(f"  选择器 {sel} 失败: {e}")
                continue

        # ── 策略 2: 降级到 <button> 标签（旧版 DeepSeek 或通用兼容）──
        button_selectors = [
            'button[aria-label="发送"]',
            'button[aria-label="发送"]:not([aria-disabled="true"])',
            'button:has-text("发送"):not([disabled])',
        ]
        for sel in button_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.count() == 0:
                    continue
                btn.wait_for(state="visible", timeout=3000)
                aria_disabled = btn.get_attribute("aria-disabled")
                if aria_disabled == "true":
                    continue
                logger.info(f"  点击 button 类型发送按钮: {sel}")
                btn.click(timeout=5000)
                logger.info("  提示词已发送")
                return True
            except Exception as e:
                logger.debug(f"  选择器 {sel} 失败: {e}")
                continue

        # ── 策略 3: XPath 万能回退 ──
        try:
            btn = self.page.locator(
                'xpath=//div[@role="button" and @aria-disabled="false"]'
            ).last
            if btn.count() > 0 and btn.is_visible(timeout=2000):
                logger.info("  通过 XPath 点击 div 类型发送按钮")
                btn.click(timeout=5000)
                logger.info("  提示词已发送")
                return True
        except Exception as e:
            logger.debug(f"  XPath div 按钮失败: {e}")

        try:
            btn = self.page.locator(
                'xpath=//button[contains(text(),"发送")]'
            ).first
            if btn.count() > 0 and btn.is_visible(timeout=2000):
                logger.info("  通过 XPath 点击 button 发送按钮")
                btn.click(timeout=5000)
                logger.info("  提示词已发送")
                return True
        except Exception as e:
            logger.debug(f"  XPath button 失败: {e}")

        logger.error("  所有发送按钮选择器均失败")
        return False

    def _wait_for_response(self) -> str:
        """等待 DeepSeek 完成回复，通过轮询内容长度判断（总超时 30s）。

        不再依赖停止按钮的出现/消失，直接轮询 markdown 元素内容：
          - 每次间隔 1s 检查最后一个助手回复的文本长度
          - 内容 > 100 字符且连续 2 次长度不变 → 认为回复完成
          - 总超时 30s 后提取已有内容
        """
        response_selectors = [
            '.ds-markdown',
            '[class*="markdown"]',
            '[class*="message"] [class*="content"]',
            '.prose',
        ]

        max_wait = 30
        poll_interval = 1.0
        last_len = 0
        stable_count = 0
        start = time.time()

        while time.time() - start < max_wait:
            time.sleep(poll_interval)

            for sel in response_selectors:
                try:
                    elements = self.page.locator(sel)
                    count = elements.count()
                    if count == 0:
                        continue

                    text = elements.last.inner_text()
                    current_len = len(text) if text else 0

                    if current_len > 100:
                        if current_len == last_len:
                            stable_count += 1
                            if stable_count >= 2:
                                logger.info(
                                    f"  回复完成 ({current_len} 字符, "
                                    f"耗时 {time.time() - start:.1f}s)"
                                )
                                return text
                        else:
                            stable_count = 0
                            last_len = current_len
                        break  # 已在此选择器找到内容，跳过其他
                except Exception:
                    continue

        # 超时回退：提取已有内容
        logger.warning(f"  等待超时 ({max_wait}s)，提取已有内容")
        for sel in response_selectors:
            try:
                elements = self.page.locator(sel)
                if elements.count() > 0:
                    text = elements.last.inner_text()
                    if text and len(text) > 20:
                        return text
            except Exception:
                continue

        body_text = self.page.locator("body").inner_text()
        return body_text

    # ── JSON 提取 ───────────────────────────────────────────────────────

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从 DeepSeek 回复文本中提取 JSON 配方。"""
        if not text:
            return None

        text_stripped = text.strip()
        try:
            return json.loads(text_stripped)
        except json.JSONDecodeError:
            pass

        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{[\s\S]*"ingredients"[\s\S]*"tools"[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{[\s\S]*?\}', text)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
                if "ingredients" in result or "tools" in result:
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法从回复中提取 JSON，回复前 300 字符: {text[:300]}")
        return None

    # ── 单批次分析 ──────────────────────────────────────────────────────

    def _analyze_batch(self, image_paths: List[Path]) -> Optional[Dict]:
        """上传一批图片，等待加载完成，发送提示词，获取分析结果。"""
        logger.info(f"批次分析 {len(image_paths)} 张图片")

        # 1. 批量上传图片
        self._upload_images_batch(image_paths)

        # 2. 等待图片加载完成（aria-disabled="false" 表示可发送）
        self._wait_for_images_loaded(len(image_paths), timeout_ms=30000)

        # 3. 发送提示词
        self._send_prompt(ANALYSIS_PROMPT)

        # 4. 等待进入分析状态（aria-disabled="true" 表示正在处理）
        self._wait_for_send_disabled(timeout_ms=10000)

        # 5. 等待回复完成
        response_text = self._wait_for_response()

        return self._extract_json(response_text)

    # ── 清除当前对话（为下一批做准备）──────────────────────────────────

    def _new_chat(self):
        """创建新对话，避免上下文污染。"""
        logger.info("  创建新对话...")
        new_chat_selectors = [
            '[aria-label*="新建" i]',
            '[aria-label*="new" i]',
            'button:has-text("新对话")',
            'button:has-text("新建")',
            '[data-testid="new-chat"]',
        ]
        for sel in new_chat_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(1.5)
                    logger.info("  新对话已创建")
                    return
            except Exception:
                continue

        # 回退：刷新页面
        logger.info("  未找到新对话按钮，刷新页面")
        self.page.reload(wait_until="domcontentloaded")
        time.sleep(2)

    # ── 主入口 ──────────────────────────────────────────────────────────

    def analyze_frames(
        self, frame_paths: List[Path], max_images: int = 5
    ) -> Dict:
        """分析多帧图片，支持多图批量上传，合并去重后返回配方 dict。

        参数:
            frame_paths: 帧图片路径列表
            max_images: 最多分析几张图（控制耗时）

        返回:
            {"ingredients": [...], "tools": [...]}
        """
        if not frame_paths:
            return {"ingredients": [], "tools": [], "error": "no_frames"}

        selected = frame_paths[:max_images]
        logger.info(f"将分析 {len(selected)}/{len(frame_paths)} 张图片")
        logger.info(f"批次大小: {self.batch_size} 张/批，共 {len(selected)} 张")

        try:
            self._ensure_logged_in()
        except Exception as e:
            logger.error(f"浏览器/登录失败: {e}")
            self._close()
            raise

        all_ingredients: Dict[str, str] = {}
        all_tools: set = set()
        success_count = 0

        # 分批处理
        batch_count = 0
        for batch_start in range(0, len(selected), self.batch_size):
            batch = selected[batch_start : batch_start + self.batch_size]
            batch_count += 1

            logger.info(f"[批次 {batch_count}] 分析 {len(batch)} 张: "
                        f"{', '.join(fp.name for fp in batch)}")

            # 如果不是第一批，创建新对话
            if batch_start > 0:
                self._new_chat()

            for attempt in range(3):
                try:
                    result = self._analyze_batch(batch)
                    if result and "error" not in result:
                        for ing in result.get("ingredients", []):
                            name = ing.get("name", "").strip()
                            amount = ing.get("amount", "适量").strip()
                            if not name:
                                continue
                            if name in all_ingredients:
                                old = all_ingredients[name]
                                if len(amount) > len(old) and old != "适量":
                                    all_ingredients[name] = amount
                            else:
                                all_ingredients[name] = amount if amount else "适量"
                        for tool in result.get("tools", []):
                            t = tool.strip() if isinstance(tool, str) else str(tool)
                            if t:
                                all_tools.add(t)
                        success_count += 1
                        logger.info(f"  批次 {batch_count} 分析成功")
                        break
                    else:
                        logger.warning(
                            f"  批次 {batch_count} 第 {attempt + 1} 次: 未提取到配方"
                        )
                except Exception as e:
                    logger.warning(
                        f"  批次 {batch_count} 第 {attempt + 1} 次异常: {e}"
                    )
                    if attempt < 2:
                        time.sleep(3)
                    else:
                        logger.error(f"  批次 {batch_count} 3 次尝试均失败")

            # 批次之间稍作间隔
            if batch_start + self.batch_size < len(selected):
                time.sleep(2)

        self._close()

        if success_count == 0:
            return {
                "ingredients": [],
                "tools": [],
                "error": "no_recipe",
                "message": (
                    "所有图片均未提取到配方。\n"
                    "可能原因：\n"
                    "  1. 图片中确实没有配方表格\n"
                    "  2. DeepSeek 网页版界面变化，选择器失效\n"
                    "  3. 网络问题导致回复超时"
                ),
            }

        ingredients_list = [
            {"name": name, "amount": amount}
            for name, amount in all_ingredients.items()
        ]

        logger.info(
            f"网页版分析完成: {len(ingredients_list)} 种食材, {len(all_tools)} 个工具"
        )
        return {
            "ingredients": ingredients_list,
            "tools": sorted(all_tools),
        }


def analyze_frames_with_deepseek_web(
    frame_paths: List[Path],
    config: Optional[dict] = None,
    max_images: int = 5,
) -> Dict:
    """便捷函数：用 DeepSeek 网页版分析图片帧，返回配方 dict。"""
    if config is None:
        config = {}
    analyzer = DeepSeekWebAnalyzer(config)
    return analyzer.analyze_frames(frame_paths, max_images=max_images)
