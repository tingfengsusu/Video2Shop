"""
Web 管理界面 — Flask 应用，提供任务管理、日志查看和在线配置编辑。

启动方式:
    python web_app.py                # 默认端口 5000
    python web_app.py --port 8080    # 自定义端口

依赖: pip install flask pyyaml
"""

import argparse
import json
import logging
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

# ── 日志配置 ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("web_app")

# ── Project paths ───────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys._MEIPASS)
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config" / "config.yaml"
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "config.default.yaml"

# ── Flask 应用 ──────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=str(PROJECT_DIR / "resources" / "templates"))

# 活跃任务 {task_id: {"status": str, "log_lines": list, "stop_event": Event,
#                     "web_port": int, "result": dict | None}}
_active_tasks: dict = {}
_tasks_lock = threading.Lock()


# ── 配置读写 ────────────────────────────────────────────────────────────


def read_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_config(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def reset_config_from_default():
    if not DEFAULT_CONFIG_PATH.exists():
        raise FileNotFoundError(f"默认配置文件不存在: {DEFAULT_CONFIG_PATH}")
    shutil.copy(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    log.info("配置已重置为默认值")


# ── 路由：页面 ──────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


# ── 路由：启动任务 ──────────────────────────────────────────────────────


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"status": "error", "message": "请提供 B站视频 URL"}), 400

    raw_url = data["url"].strip()
    if not raw_url:
        return jsonify({"status": "error", "message": "URL 不能为空"}), 400

    task_id = uuid.uuid4().hex[:12]
    stop_event = threading.Event()
    log_lines = []

    # 确定 web_interface 端口（避免与 web_app 冲突）
    try:
        cfg = read_config()
        web_port = cfg.get("web", {}).get("port", 5000)
    except Exception:
        web_port = 5000
    web_interface_port = web_port + 1

    with _tasks_lock:
        _active_tasks[task_id] = {
            "status": "running",
            "log_lines": log_lines,
            "stop_event": stop_event,
            "web_port": web_interface_port,
            "result": None,
        }

    # 在后台线程中运行管道
    def _run():
        from pipeline import run_pipeline

        def log_cb(msg: str):
            log_lines.append(msg)

        result = run_pipeline(
            url=raw_url,
            config_path=str(CONFIG_PATH),
            log_callback=log_cb,
            stop_event=stop_event,
        )

        with _tasks_lock:
            task = _active_tasks.get(task_id)
            if task:
                task["status"] = "done" if result.get("success") else "failed"
                task["result"] = result

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    with _tasks_lock:
        _active_tasks[task_id]["thread"] = thread

    log.info(f"任务 {task_id} 已启动，配方界面端口: {web_interface_port}")
    return jsonify({
        "status": "ok",
        "task_id": task_id,
        "message": f"任务已启动，完成后将在 http://127.0.0.1:{web_interface_port} 展示配方",
    })


# ── 路由：日志轮询 ──────────────────────────────────────────────────────


@app.route("/api/logs/<task_id>")
def api_logs(task_id):
    offset = request.args.get("offset", 0, type=int)

    with _tasks_lock:
        task = _active_tasks.get(task_id)

    if task is None:
        return jsonify({"logs": "", "offset": offset, "done": True, "not_found": True})

    log_lines = task["log_lines"]
    new_lines = log_lines[offset:]
    new_offset = len(log_lines)

    return jsonify({
        "logs": "\n".join(new_lines),
        "offset": new_offset,
        "done": task["status"] in ("done", "failed", "stopped"),
        "status": task["status"],
        "web_port": task.get("web_port"),
    })


# ── 路由：任务状态 ──────────────────────────────────────────────────────


@app.route("/api/task/<task_id>")
def api_task_status(task_id):
    with _tasks_lock:
        task = _active_tasks.get(task_id)
    if task is None:
        return jsonify({"status": "error", "message": "任务不存在"}), 404

    result = task.get("result")
    return jsonify({
        "task_id": task_id,
        "status": task["status"],
        "web_port": task.get("web_port"),
        "result": result,
    })


# ── 路由：配置管理 ──────────────────────────────────────────────────────


@app.route("/api/config", methods=["GET"])
def api_get_config():
    try:
        return jsonify({"status": "ok", "config": read_config()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "无效数据"}), 400

    try:
        cfg = read_config()

        for key, val in data.items():
            if key.startswith("_"):
                continue
            keys = key.split(".")
            d = cfg
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            d[keys[-1]] = val

        write_config(cfg)
        log.info("配置已保存")
        return jsonify({"status": "ok", "message": "配置已保存"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/config/reset", methods=["POST"])
def api_reset_config():
    try:
        reset_config_from_default()
        return jsonify({"status": "ok", "message": "已恢复默认配置", "config": read_config()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── 清理 ────────────────────────────────────────────────────────────────


@app.route("/api/stop/<task_id>", methods=["POST"])
def api_stop_task(task_id):
    with _tasks_lock:
        task = _active_tasks.get(task_id)
    if task is None:
        return jsonify({"status": "error", "message": "任务不存在"}), 404

    task["stop_event"].set()
    task["status"] = "stopped"
    return jsonify({"status": "ok"})


# ── 启动 ────────────────────────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(description="Video2Shop Web 管理界面")
    parser.add_argument("--port", "-p", type=int, default=None, help="Web 服务器端口")
    parser.add_argument("--host", default=None, help="绑定地址")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        cfg = read_config()
    except Exception:
        cfg = {}
    web_cfg = cfg.get("web", {})
    host = args.host or web_cfg.get("host", "127.0.0.1")
    port = args.port or web_cfg.get("port", 5000)

    print(f"\n{'=' * 50}")
    print(f"  Video2Shop Web 管理界面")
    print(f"  地址: http://{host}:{port}")
    print(f"  设置: http://{host}:{port}/settings")
    print(f"  按 Ctrl+C 停止服务器")
    print(f"{'=' * 50}\n")

    werkzeug_log = logging.getLogger("werkzeug")
    werkzeug_log.setLevel(logging.WARNING)

    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
