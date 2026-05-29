"""
启动前检查模块 — 验证 DeepSeek 网页登录态 / JD 登录态 / API Key。

在程序启动时自动检测当前分析模式所需的前置条件是否满足，
缺少则引导用户打开浏览器完成登录，保存 cookie 后继续。
"""

import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

logger = logging.getLogger("preflight")


class CheckStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    FAILED = "failed"
    SKIPPED = "skipped"


class PreflightCheck:
    """启动前检查：按需验证并修复 auth 前置条件。"""

    def __init__(
        self,
        config: dict,
        config_path: str = "config/config.yaml",
        status_callback: Optional[Callable[[str, CheckStatus, str], None]] = None,
    ):
        self.config = config
        self.config_path = Path(config_path)
        self._status_cb = status_callback
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _report(self, name: str, status: CheckStatus, detail: str = ""):
        if self._status_cb:
            self._status_cb(name, status, detail)

    # ── 主入口 ──────────────────────────────────────────────────────────

    def run_all(self) -> Dict[str, CheckStatus]:
        """运行所有相关检查，缺少时引导修复。返回各检查项状态。"""
        results = {}

        analysis_mode = self.config.get("deepseek", {}).get("analysis_mode", "api")

        # 1. API Key 检查（api 模式必需）
        if analysis_mode == "api":
            results["api_key"] = self.ensure_api_key()

        # 2. DeepSeek 网页登录态（web 模式必需）
        if analysis_mode == "web":
            results["deepseek_web"] = self.ensure_deepseek_web()

        # 3. JD 登录态（加购功能总是需要）
        results["jd"] = self.ensure_jd()

        return results

    # ── API Key ─────────────────────────────────────────────────────────

    def check_api_key(self) -> tuple[CheckStatus, str]:
        api_key = self.config.get("deepseek", {}).get("api_key", "")
        if api_key:
            return CheckStatus.OK, "已配置"
        # 环境变量备选
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        if os.getenv("DEEPSEEK_API_KEY"):
            return CheckStatus.OK, "来自环境变量"
        return CheckStatus.MISSING, "未配置 API Key"

    def ensure_api_key(self) -> CheckStatus:
        status, detail = self.check_api_key()
        if status == CheckStatus.OK:
            logger.info(f"  API Key: {detail}")
        else:
            logger.warning(f"  API Key: {detail}（可在设置页面填写）")
        self._report("API Key", status, detail)
        return status

    # ── DeepSeek 网页登录态 ─────────────────────────────────────────────

    def ensure_deepseek_web(self) -> CheckStatus:
        """启动浏览器验证 DeepSeek 登录态。加载已有 cookie 打开网页，
        检查是否已登录，未登录则等待用户扫码，cookie 自动保存。"""
        logger.info("  DeepSeek 网页: 启动浏览器验证...")
        self._report("DeepSeek 网页", CheckStatus.MISSING, "正在打开浏览器验证登录态...")
        return self._setup_deepseek_web_cookies()

    def _setup_deepseek_web_cookies(self) -> CheckStatus:
        """打开浏览器引导用户登录 DeepSeek，保存 cookies。"""
        try:
            from playwright.sync_api import sync_playwright

            ds_web = self.config.get("deepseek_web", {})
            cookies_file = Path(ds_web.get("cookies_file", "config/deepseek_auth.json"))
            headless = ds_web.get("headless", False)

            self._pw = sync_playwright().start()

            # 用系统 Chrome 启动
            try:
                self._browser = self._pw.chromium.launch(
                    channel="chrome",
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                self._browser = self._pw.chromium.launch(
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )

            # 加载已有登录态
            if cookies_file.exists():
                self._context = self._browser.new_context(
                    storage_state=str(cookies_file)
                )
            else:
                self._context = self._browser.new_context()
            self._page = self._context.new_page()

            self._page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded")

            # 检查是否已登录
            if self._has_valid_deepseek_session():
                self._context.storage_state(path=str(cookies_file))
                logger.info("DeepSeek 登录态有效，已保存")
                self._report("DeepSeek 网页", CheckStatus.OK, "登录态已保存")
                return CheckStatus.OK

            # 等待用户登录
            logger.info("请在浏览器窗口中完成 DeepSeek 登录（5 分钟超时）...")
            self._report("DeepSeek 网页", CheckStatus.MISSING, "请在浏览器中登录 DeepSeek...")

            cookies_file.parent.mkdir(parents=True, exist_ok=True)
            start = time.time()
            while time.time() - start < 300:
                time.sleep(2)
                if self._has_valid_deepseek_session():
                    self._context.storage_state(path=str(cookies_file))
                    logger.info("DeepSeek 登录成功，cookie 已保存")
                    self._report("DeepSeek 网页", CheckStatus.OK, "登录成功")
                    return CheckStatus.OK

            self._report("DeepSeek 网页", CheckStatus.FAILED, "登录超时")
            return CheckStatus.FAILED

        except Exception as e:
            logger.error(f"DeepSeek 登录引导失败: {e}")
            self._report("DeepSeek 网页", CheckStatus.FAILED, str(e))
            return CheckStatus.FAILED
        finally:
            self._close_browser()

    def _has_valid_deepseek_session(self) -> bool:
        try:
            # 先检查是否未登录 — 有"登录"按钮说明未登录
            try:
                login_btn = self._page.locator(
                    'button:has-text("登录"), a:has-text("登录"), '
                    '[class*="login"]:has-text("登录")'
                ).first
                if login_btn.is_visible(timeout=2000):
                    return False
            except Exception:
                pass

            # 已登录 — 有聊天输入框且没有登录按钮
            self._page.wait_for_selector(
                'textarea, [contenteditable="true"], [role="textbox"]',
                timeout=6000,
            )
            return True
        except Exception:
            return False

    # ── JD 登录态 ───────────────────────────────────────────────────────

    def ensure_jd(self) -> CheckStatus:
        """启动浏览器验证京东登录态。始终用程序自己的 profile 打开浏览器，
        导航到 jd.com 检查登录，未登录则等待用户扫码，cookie 自动持久化。"""
        logger.info("  京东登录: 启动浏览器验证...")
        self._report("京东登录", CheckStatus.MISSING, "正在打开浏览器验证登录态...")
        return self._setup_jd_cookies()

    def _setup_jd_cookies(self) -> CheckStatus:
        """启动浏览器引导用户登录京东，登录态持久化到 user-data-dir。"""
        try:
            from playwright.sync_api import sync_playwright
            import os

            shop_cfg = self.config.get("shopping", {})
            user_data_dir = str(
                Path(os.environ.get("TEMP", "/tmp")) / "chrome-playwright-profile"
            )
            debug_port = shop_cfg.get("debug_port", 9222)

            self._pw = sync_playwright().start()

            # 直接用 launch_persistent_context 确保持久化到正确的 profile
            logger.info("正在启动 Chrome 浏览器...")

            self._browser = self._pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel="chrome",
                args=[
                    f"--remote-debugging-port={debug_port}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1200,800",
                ],
            )
            self._context = self._browser
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()

            # 确保浏览器窗口在前台
            try:
                self._page.bring_to_front()
            except Exception:
                pass

            self._page.goto("https://www.jd.com/", wait_until="load", timeout=30000)
            time.sleep(5)

            if self._has_valid_jd_session():
                logger.info("京东已登录，无需重复登录")
                self._report("京东登录", CheckStatus.OK, "已登录（浏览器自动关闭）")
                return CheckStatus.OK

            # 等待用户登录
            logger.info("=" * 50)
            logger.info("请在浏览器窗口中登录京东（扫码或账号密码）")
            logger.info("登录成功后程序自动继续...")
            logger.info("=" * 50)
            self._report("京东登录", CheckStatus.MISSING, "请在浏览器中扫码登录京东...")

            start = time.time()
            while time.time() - start < 300:
                time.sleep(2)
                if self._has_valid_jd_session():
                    logger.info("京东登录成功！")
                    self._report("京东登录", CheckStatus.OK, "登录成功")
                    return CheckStatus.OK

            self._report("京东登录", CheckStatus.FAILED, "登录超时（5分钟）")
            return CheckStatus.FAILED

        except Exception as e:
            logger.error(f"JD 登录引导失败: {e}")
            self._report("京东登录", CheckStatus.FAILED, str(e))
            return CheckStatus.FAILED
        finally:
            self._close_browser()

    def _has_valid_jd_session(self) -> bool:
        try:
            # 先检查未登录标志 — "请登录" 链接可见则一定未登录
            try:
                logout_hint = self._page.locator('a:has-text("请登录")').first
                if logout_hint.is_visible(timeout=1000):
                    return False
            except Exception:
                pass

            # 已登录才出现的元素
            logged_in_sel = [
                'text=退出登录',
                'a:has-text("退出登录")',
                '.nickname',
                '[class*="nickname"]',
                '.user-name',
            ]
            for sel in logged_in_sel:
                try:
                    if self._page.locator(sel).first.is_visible(timeout=1000):
                        return True
                except Exception:
                    continue

            # cookie 兜底
            if self._context:
                cookies = self._context.cookies()
                for c in cookies:
                    if c.get("name") in ("pin", "pt_pin", "pwdt_id"):
                        return True
            return False
        except Exception:
            return False

    # ── 清理 ────────────────────────────────────────────────────────────

    def _close_browser(self):
        if self._page and not self._page.is_closed():
            try:
                self._page.close()
            except Exception:
                pass
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None


# ── 便捷入口 ──────────────────────────────────────────────────────────────

def run_preflight(
    config_path: str = "config/config.yaml",
    status_callback: Optional[Callable[[str, CheckStatus, str], None]] = None,
) -> Dict[str, CheckStatus]:
    """便捷入口：加载配置 → 运行所有检查 → 返回结果。"""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"配置文件不存在: {config_path}")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    checker = PreflightCheck(config, config_path, status_callback)
    return checker.run_all()
