"""
Web 交互模块：Flask 服务器 + 交互式 HTML 页面。
用户确认配方清单，勾选已有物品 → 点击生成购物车 → 自动打开京东加购。
"""

import json
import logging
import threading
import time
import webbrowser
from typing import Dict, Any

from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)

# HTML 模板
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>视频配方提取 - 购物清单</title>
<style>
    :root {
        --bg: #f5f5f5;
        --card-bg: #ffffff;
        --text: #333333;
        --sub: #666666;
        --accent: #e4393c;
        --accent-hover: #c1272d;
        --border: #e0e0e0;
        --tag-bg: #fff3f3;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        background: var(--bg);
        color: var(--text);
        min-height: 100vh;
        padding: 20px;
    }
    .header {
        text-align: center;
        padding: 30px 20px;
        margin-bottom: 20px;
    }
    .header h1 { font-size: 28px; margin-bottom: 8px; }
    .header p { color: var(--sub); font-size: 14px; }
    .container {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
        max-width: 1000px;
        margin: 0 auto;
    }
    @media (max-width: 640px) {
        .container { grid-template-columns: 1fr; }
    }
    .card {
        background: var(--card-bg);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .card h2 {
        font-size: 20px;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .card .count { font-size: 13px; color: var(--sub); font-weight: normal; }
    .card .select-actions {
        margin-left: auto;
        display: flex;
        gap: 6px;
    }
    .card .select-actions span {
        font-size: 12px;
        color: var(--accent);
        cursor: pointer;
        user-select: none;
        padding: 2px 8px;
        border: 1px solid var(--accent);
        border-radius: 4px;
        transition: all 0.15s;
    }
    .card .select-actions span:hover {
        background: var(--accent);
        color: #fff;
    }
    .item-list { margin-top: 16px; }
    .item {
        display: flex;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--border);
        gap: 10px;
    }
    .item:last-child { border-bottom: none; }
    .item input[type="checkbox"] {
        width: 18px; height: 18px;
        accent-color: var(--accent);
        flex-shrink: 0;
        cursor: pointer;
    }
    .item label {
        flex: 1;
        cursor: pointer;
        font-size: 15px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .item .amount {
        font-size: 13px;
        color: var(--sub);
        background: var(--tag-bg);
        padding: 2px 8px;
        border-radius: 4px;
    }
    .empty { color: var(--sub); text-align: center; padding: 20px; font-size: 14px; }
    .action-area {
        max-width: 1000px;
        margin: 30px auto 0;
        text-align: center;
    }
    .btn-generate {
        background: var(--accent);
        color: white;
        border: none;
        padding: 14px 48px;
        font-size: 17px;
        border-radius: 8px;
        cursor: pointer;
        font-weight: 600;
        transition: background 0.2s;
    }
    .btn-generate:hover { background: var(--accent-hover); }
    .btn-generate:disabled {
        background: #ccc;
        cursor: not-allowed;
    }

    /* 进度区域 */
    .progress-area {
        max-width: 1000px;
        margin: 24px auto 0;
        display: none;
    }
    .progress-area.show { display: block; }
    .progress-card {
        background: var(--card-bg);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        text-align: center;
    }
    .progress-bar {
        width: 100%;
        height: 8px;
        background: #eee;
        border-radius: 4px;
        margin: 16px 0;
        overflow: hidden;
    }
    .progress-fill {
        height: 100%;
        background: var(--accent);
        border-radius: 4px;
        transition: width 0.3s;
        width: 0%;
    }
    .progress-text {
        font-size: 14px;
        color: var(--sub);
        margin-top: 8px;
    }
    .progress-items {
        text-align: left;
        max-height: 200px;
        overflow-y: auto;
        margin-top: 12px;
    }
    .progress-item {
        padding: 6px 0;
        font-size: 13px;
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .progress-item .status {
        width: 20px;
        text-align: center;
    }
    .progress-item .status.ok { color: #52c41a; }
    .progress-item .status.fail { color: #ff4d4f; }
    .progress-item .status.pending { color: #ccc; }
    .btn-open-cart {
        margin-top: 16px;
        background: #fff;
        color: var(--accent);
        border: 2px solid var(--accent);
        padding: 10px 32px;
        font-size: 15px;
        border-radius: 8px;
        cursor: pointer;
        font-weight: 600;
        transition: all 0.2s;
        display: none;
    }
    .btn-open-cart.show { display: inline-block; }
    .btn-open-cart:hover { background: #fff5f5; }
    .toast {
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: #333;
        color: #fff;
        padding: 10px 24px;
        border-radius: 6px;
        font-size: 14px;
        z-index: 999;
        opacity: 0;
        transition: opacity 0.3s;
        pointer-events: none;
    }
    .toast.show { opacity: 1; }
</style>
</head>
<body>

<div class="header">
    <h1>🛒 配方购物清单</h1>
    <p>勾选您<b>已经拥有</b>的食材和工具，未勾选的将自动加入京东购物车</p>
</div>

<div class="container">
    <!-- 食材清单 -->
    <div class="card" id="ingredients-card">
        <h2>
            📦 食材清单
            <span class="count" id="ingr-count"></span>
            <span class="select-actions">
                <span onclick="selectAll('ingredients')">全选</span>
                <span onclick="selectNone('ingredients')">全不选</span>
            </span>
        </h2>
        <div class="item-list" id="ingredients-list"></div>
    </div>

    <!-- 工具清单 -->
    <div class="card" id="tools-card">
        <h2>
            🔧 工具清单
            <span class="count" id="tools-count"></span>
            <span class="select-actions">
                <span onclick="selectAll('tools')">全选</span>
                <span onclick="selectNone('tools')">全不选</span>
            </span>
        </h2>
        <div class="item-list" id="tools-list"></div>
    </div>
</div>

<div class="action-area">
    <button class="btn-generate" id="btn-generate" onclick="generateCart()">
        🛍️ 生成购物车 — 自动加购京东
    </button>
</div>

<div class="progress-area" id="progress-area">
    <div class="progress-card">
        <h3 id="progress-title">⏳ 正在处理...</h3>
        <div class="progress-bar">
            <div class="progress-fill" id="progress-fill"></div>
        </div>
        <div class="progress-text" id="progress-text"></div>
        <div class="progress-items" id="progress-items"></div>
        <button class="btn-open-cart" id="btn-open-cart" onclick="openCart()">
            🚀 查看京东购物车
        </button>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const INGREDIENTS = __INGREDIENTS__;
const TOOLS = __TOOLS__;

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function renderList(containerId, items, isIngredient) {
    const container = document.getElementById(containerId);
    if (!items || items.length === 0) {
        container.innerHTML = '<div class="empty">暂无数据</div>';
        return;
    }
    let html = "";
    items.forEach((item, idx) => {
        const name = isIngredient ? item.name : item;
        const amount = isIngredient ? (item.amount || "适量") : "";
        const id = (isIngredient ? "ingr" : "tool") + "_" + idx;
        html += `<div class="item">
            <input type="checkbox" id="${id}" checked data-name="${escapeHtml(name)}">
            <label for="${id}">
                ${escapeHtml(name)}
                ${amount ? `<span class="amount">${escapeHtml(amount)}</span>` : ""}
            </label>
        </div>`;
    });
    container.innerHTML = html;
}

function countChecked(type) {
    const listId = type === "ingredients" ? "ingredients-list" : "tools-list";
    return document.querySelectorAll(`#${listId} input:checked`).length;
}

function countTotal(type) {
    return type === "ingredients" ? INGREDIENTS.length : TOOLS.length;
}

function updateCounts() {
    const ingrChecked = countChecked("ingredients");
    document.getElementById("ingr-count").textContent = `(${ingrChecked}/${INGREDIENTS.length} 已拥有)`;
    const toolsChecked = countChecked("tools");
    document.getElementById("tools-count").textContent = `(${toolsChecked}/${TOOLS.length} 已拥有)`;
}

function selectAll(type) {
    const listId = type === "ingredients" ? "ingredients-list" : "tools-list";
    document.querySelectorAll(`#${listId} input[type="checkbox"]`).forEach(cb => { cb.checked = true; });
    updateCounts();
}

function selectNone(type) {
    const listId = type === "ingredients" ? "ingredients-list" : "tools-list";
    document.querySelectorAll(`#${listId} input[type="checkbox"]`).forEach(cb => { cb.checked = false; });
    updateCounts();
}

function collectMissing() {
    // 收集所有未被勾选的物品（用户不需要购买的 = 需要加购的）
    const missing = [];
    const ingrCbs = document.querySelectorAll("#ingredients-list input[type=\"checkbox\"]");
    const toolCbs = document.querySelectorAll("#tools-list input[type=\"checkbox\"]");

    ingrCbs.forEach(cb => {
        if (!cb.checked) {
            const name = cb.getAttribute("data-name") || "";
            if (name) missing.push(name);
        }
    });
    toolCbs.forEach(cb => {
        if (!cb.checked) {
            const name = cb.getAttribute("data-name") || "";
            if (name) missing.push(name);
        }
    });

    console.log("[collectMissing] 食材复选框:", ingrCbs.length, "个,",
                "已勾选:", Array.from(ingrCbs).filter(c => c.checked).length,
                "未勾选:", Array.from(ingrCbs).filter(c => !c.checked).length);
    console.log("[collectMissing] 工具复选框:", toolCbs.length, "个,",
                "已勾选:", Array.from(toolCbs).filter(c => c.checked).length,
                "未勾选:", Array.from(toolCbs).filter(c => !c.checked).length);
    console.log("[collectMissing] 将发送给后端的物品:", JSON.stringify(missing));

    return missing;
}

async function generateCart() {
    const missing = collectMissing();
    const btn = document.getElementById("btn-generate");
    const progressArea = document.getElementById("progress-area");

    if (missing.length === 0) {
        document.getElementById("progress-title").textContent = "🎉 太棒了！你已拥有所有物品，无需购买。";
        document.getElementById("progress-text").textContent = "";
        document.getElementById("progress-items").innerHTML = "";
        progressArea.classList.add("show");
        progressArea.scrollIntoView({ behavior: "smooth" });
        return;
    }

    // 禁用按钮
    btn.disabled = true;
    btn.textContent = "⏳ 正在加购...";

    // 显示进度区域
    progressArea.classList.add("show");
    document.getElementById("progress-title").textContent =
        `⏳ 正在京东自动加购 ${missing.length} 件商品...`;
    document.getElementById("progress-items").innerHTML = missing.map((name, i) =>
        `<div class="progress-item" id="pitem-${i}">
            <span class="status pending">○</span>
            <span>${escapeHtml(name)}</span>
        </div>`
    ).join("");
    progressArea.scrollIntoView({ behavior: "smooth" });

    // 调用后端 API
    const payload = { items: missing };
    console.log("[generateCart] POST /api/generate-cart payload:", JSON.stringify(payload));

    try {
        const resp = await fetch("/api/generate-cart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const result = await resp.json();

        if (result.status === "ok") {
            // 标记所有项目成功
            result.results.forEach((r, i) => {
                const el = document.getElementById(`pitem-${i}`);
                if (el) {
                    const icon = r.success ? "✓" : "✗";
                    const cls = r.success ? "ok" : "fail";
                    el.querySelector(".status").textContent = icon;
                    el.querySelector(".status").className = "status " + cls;
                }
            });

            const okCount = result.results.filter(r => r.success).length;
            document.getElementById("progress-title").textContent =
                `✅ 加购完成: ${okCount}/${result.results.length} 件`;
            document.getElementById("progress-fill").style.width = "100%";
            document.getElementById("progress-text").textContent =
                "浏览器正在跳转到京东购物车页面...";

            // 显示"查看购物车"按钮
            const cartBtn = document.getElementById("btn-open-cart");
            cartBtn.classList.add("show");

            // 提示用户在浏览器中确认
            showToast(`加购完成: ${okCount}/${result.results.length}。请查看浏览器中打开的京东页面。`);
        } else {
            document.getElementById("progress-title").textContent = "❌ 加购失败";
            document.getElementById("progress-text").textContent =
                result.message || "未知错误";
        }
    } catch (e) {
        document.getElementById("progress-title").textContent = "❌ 请求失败";
        document.getElementById("progress-text").textContent = String(e);
    }

    btn.disabled = false;
    btn.textContent = "🛍️ 生成购物车 — 自动加购京东";
}

function openCart() {
    // 通过后端 API 告知跳转购物车页面（后端已打开浏览器，这里只是导航提示）
    fetch("/api/open-cart", { method: "POST" })
        .then(() => showToast("请在已打开的京东浏览器窗口中查看购物车"))
        .catch(() => showToast("请在已打开的京东浏览器窗口中查看购物车"));
}

function showToast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 3000);
}

document.addEventListener("DOMContentLoaded", () => {
    renderList("ingredients-list", INGREDIENTS, true);
    renderList("tools-list", TOOLS, false);
    updateCounts();
    document.querySelectorAll(".item-list").forEach(list => {
        list.addEventListener("change", updateCounts);
    });
});
</script>
</body>
</html>"""


def build_page_html(ingredients: list, tools: list) -> str:
    """将配方数据注入 HTML 模板。"""
    ingredients_json = json.dumps(ingredients, ensure_ascii=False)
    tools_json = json.dumps(tools, ensure_ascii=False)
    html = PAGE_TEMPLATE.replace("__INGREDIENTS__", ingredients_json)
    html = html.replace("__TOOLS__", tools_json)
    return html


class WebServer:
    """本地 Flask Web 服务器，展示交互式配方确认页面 + 京东加购。"""

    def __init__(self, config: dict):
        web_cfg = config.get("web", {})
        self.host = web_cfg.get("host", "127.0.0.1")
        self.port = web_cfg.get("port", 5000)
        self.auto_open = web_cfg.get("auto_open_browser", True)

        self.app = Flask(__name__)
        self.ingredients: list = []
        self.tools: list = []
        self._jd_handler = None
        self._shopping_config = config.get("shopping", {})
        self._config = config
        self._setup_routes()

    def set_recipe_data(self, ingredients: list, tools: list):
        """设置配方数据（在启动前调用）。"""
        self.ingredients = ingredients
        self.tools = tools

    def _setup_routes(self):
        app = self.app

        @app.route("/")
        def index():
            html = build_page_html(self.ingredients, self.tools)
            return html

        @app.route("/api/recipe")
        def get_recipe():
            return jsonify({
                "ingredients": self.ingredients,
                "tools": self.tools,
            })

        @app.route("/api/generate-cart", methods=["POST"])
        @app.route("/add_to_cart", methods=["POST"])
        def generate_cart():
            """接收前端提交的未勾选物品列表，后台自动加购京东。

            前端 POST JSON: {"items": ["物品1", "物品2", ...]}
            只对接收到的缺失物品调用 JdHandler.search_and_add。
            """
            data = request.get_json()
            if not data or "items" not in data:
                return jsonify({"status": "error", "message": "无效请求，缺少 items 字段"}), 400

            items = data["items"]
            # 过滤空字符串
            items = [item for item in items if item and isinstance(item, str) and item.strip()]
            if not items:
                return jsonify({"status": "ok", "results": [], "message": "无需购买"})

            logger.info(f"收到加购请求: {len(items)} 件商品")
            for i, item in enumerate(items):
                logger.info(f"  [{i+1}] {item}")

            results = []
            handler = None
            try:
                from shopping_platform import JdHandler

                handler = JdHandler(
                    debug_port=self._shopping_config.get("debug_port", 9222),
                    auto_launch=self._shopping_config.get("auto_launch", True),
                    close_browser_on_exit=self._shopping_config.get("close_browser_on_exit", False),
                    search_timeout=self._shopping_config.get("search_timeout", 10000),
                    add_cart_retry=self._shopping_config.get("add_cart_retry", 2),
                    add_cart_delay=self._shopping_config.get("add_cart_delay", 0.5),
                    click_retry=self._shopping_config.get("click_retry", 1),
                    search_wait_after=self._shopping_config.get("search_wait_after", 1.0),
                    retry_on_failure=self._shopping_config.get("retry_on_failure", True),
                    chrome_path=self._shopping_config.get("chrome_path", ""),
                )

                # 连接 Chrome（CDP 模式）
                handler.login()

                # 依次搜索加购
                for i, keyword in enumerate(items):
                    logger.info(f"[{i+1}/{len(items)}] 加购: {keyword}")
                    success = handler.search_and_add(keyword)
                    results.append({
                        "keyword": keyword,
                        "success": success,
                    })
                    # 物品之间稍作间隔
                    if i < len(items) - 1:
                        time.sleep(1.5)

                # 全部完成后跳转到购物车页面
                handler.open_cart_page()
                logger.info(f"加购完成: {sum(1 for r in results if r['success'])}/{len(results)} 成功")

            except Exception as e:
                logger.error(f"加购流程异常: {e}")
                return jsonify({
                    "status": "error",
                    "message": f"加购流程异常: {str(e)}",
                    "results": results,
                }), 500
            finally:
                # 保存 handler 引用，用于后续 open-cart 请求
                self._jd_handler = handler
                # 注意：不在这里 close browser，因为购物车页面还需要查看

            return jsonify({
                "status": "ok",
                "results": results,
                "total": len(results),
                "success_count": sum(1 for r in results if r["success"]),
            })

        @app.route("/api/open-cart", methods=["POST"])
        def open_cart():
            """跳转到京东购物车页面。"""
            if self._jd_handler:
                try:
                    self._jd_handler.open_cart_page()
                except Exception as e:
                    logger.warning(f"跳转购物车失败: {e}")
            return jsonify({"status": "ok"})

    def _open_browser(self):
        """在新线程中延迟打开浏览器，确保服务器已启动。"""
        def _open():
            time.sleep(0.5)
            url = f"http://{self.host}:{self.port}"
            webbrowser.open(url)
            logger.info(f"浏览器已打开: {url}")

        t = threading.Thread(target=_open, daemon=True)
        t.start()

    def start(self):
        """启动 Flask 服务器。"""
        if self.auto_open:
            self._open_browser()

        logger.info(f"Web 服务器启动: http://{self.host}:{self.port}")
        logger.info("按 Ctrl+C 停止服务器")
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def cleanup(self):
        """清理京东浏览器资源。"""
        if self._jd_handler:
            try:
                self._jd_handler.close()
            except Exception:
                pass
            self._jd_handler = None
