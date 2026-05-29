# 🎬 Video2Shop

**B站视频 → AI 配方提取 → 京东一键加购**

从 B站美食/手工视频中自动提取配方（食材 + 工具），勾选已有物品后在京东一键加购缺失的部分。

<p align="center">
  <img src="docs/screenshot.png" alt="截图" width="800">
  <br>
  <em>↑ 演示截图 — 替换为实际截图</em>
</p>

---

## ✨ 功能特性

- 🎥 **智能视频分析** — 输入 B站视频链接，自动下载 → 关键帧抽取 → OCR 文字筛选
- 🤖 **双模式 AI 配方提取** — 支持 DeepSeek API (V4 Flash) 直连 + 网页版两种模式，设置中一键切换
- 🔧 **启动前自动检查** — 自动打开浏览器引导登录京东/DeepSeek，扫码即可完成，无需手动操作
- ✅ **已有物品勾选** — 可视化复选框界面，标记你已拥有的物品
- 🛒 **一键京东加购** — 程序自动启动 Chrome 保持登录态，自动搜索自营商品并加入购物车
- 🖥️ **三种使用方式** — 命令行 / 桌面 GUI / Web 前端，共享同一套后端管道
- ⚙️ **在线配置** — GUI 内置设置面板，修改即时生效，无需手动编辑 YAML
- 📦 **开箱即用** — 内置 ffmpeg + PyTorch + EasyOCR，解压即用，无需安装任何依赖
- 🚀 **快速构建** — auto_build.py 一键打包 (~2.5 分钟)，自动下载 UPX 压缩

---

## 🚀 快速开始

### 方式 A：下载打包好的版本（推荐）

1. 从 [Releases](../../releases) 下载 `Video2Shop_vX.Y.Z.zip`
2. 解压到任意目录
3. 确保系统已安装 **Google Chrome**（京东加购需要）
4. 双击运行 `Video2Shop/Video2Shop.exe`

首次运行会：
- 自动创建 `config.yaml` 配置文件
- 自动下载 EasyOCR 中文识别模型到 `~/.EasyOCR/`（约 100MB，仅首次）

### 方式 B：从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/Video2Shop.git
cd Video2Shop

# 2. 安装依赖
pip install -r requirements.txt
pip install ttkbootstrap          # GUI 美化主题（可选）

# 3. 安装 Playwright 浏览器（DeepSeek 网页版需要）
playwright install chromium

# 4. 下载 ffmpeg（DASH 音视频合并需要）
#    从 https://www.gyan.dev/ffmpeg/builds/ 下载 ffmpeg-release-essentials.zip
#    解压后将 ffmpeg.exe 放入 tools/ 目录
#    使用打包好的版本则无需此步骤

# 5. 启动
python src/gui.py                     # 桌面 GUI
# python src/main.py --url BV1xxx     # 命令行
# python src/web_app.py               # Web 前端 (http://127.0.0.1:5000)
```

---

## 🔧 配置文件

首次运行时自动从 `config.default.yaml` 生成 `config.yaml`。也可以通过 GUI 的「设置」面板在线修改。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `deepseek.analysis_mode` | 配方提取方式 | `api` |
| `deepseek.api_key` | DeepSeek API Key | (空) |
| `deepseek.model` | API 模型 | `deepseek-v4-flash` |
| `shopping.chrome_path` | 自定义浏览器路径 | (空) |
| `shopping.add_cart_delay` | 加购后延迟(秒) | `0.5` |
| `shopping.click_retry` | 加购按钮点击重试 | `1` |
| `video.frame_interval` | 视频抽帧间隔(秒) | `5` |
| `video.max_frames` | 最大抽帧数 | `20` |
| `ocr.min_chinese_chars` | 最少中文字符数 | `25` |
| `deepseek_web.timeout_seconds` | AI 回复超时(秒) | `120` |
| `deepseek_web.batch_size` | 每批上传图片数 | `5` |
| `gui.startup_check` | 启动时自动检查 | `true` |
| `gui.log_level` | GUI 日志级别 | `INFO` |

完整配置项请查看 [`config/config.default.yaml`](config/config.default.yaml)。

---

## 🏗️ 项目结构

```
Video2Shop/
├── src/                           # Python source code
│   ├── gui.py                     # Desktop GUI entry (Tkinter + ttkbootstrap)
│   ├── main.py                    # CLI entry
│   ├── web_app.py                 # Web frontend entry (Flask)
│   ├── pipeline.py                # Shared backend pipeline
│   ├── video_processor.py         # Video download + frame extraction + OCR
│   ├── deepseek_web_analyzer.py   # DeepSeek web multi-image analysis
│   ├── recipe_extractor.py        # DeepSeek API recipe extraction (V4 Flash)
│   ├── shopping_platform.py       # JD shopping cart automation (Playwright)
│   ├── web_interface.py           # Web recipe display + cart interface
│   ├── bili_downloader.py         # Bilibili video downloader (durl + DASH/ffmpeg)
│   ├── preflight.py               # Startup auth check + browser-guided login
│   └── utils.py                   # Shared utilities (ffmpeg path resolver)
├── config/                        # Configuration files
│   ├── config.default.yaml        # Default config template
│   └── config.yaml                # Runtime config (gitignored)
├── resources/                     # Static resources
│   └── templates/                 # Web frontend HTML templates
├── scripts/                       # Helper scripts
│   ├── build.bat                  # PyInstaller build script (onedir + UPX)
│   ├── build.py                   # Cross-platform build script
│   └── setup.iss                  # Inno Setup installer config
├── tools/                         # Bundled executables
│   ├── .gitkeep
│   └── ffmpeg.exe                 # (gitignored, download separately)
├── temp/                          # Temporary files (gitignored)
├── tests/                         # Unit tests
├── requirements.txt               # Python dependencies
├── requirements-gui.txt           # GUI extra dependencies
├── .gitignore
└── README.md
```

---

## 📦 打包

### 快速打包

```batch
scripts\build.bat
```

或跨平台：

```bash
python scripts/build.py
python auto_build.py
```

### 打包流程

| 步骤 | 说明 |
|------|------|
| `--onedir` | 生成 `dist/Video2Shop/` 文件夹，启动无需解压 |
| UPX 压缩 | 自动检测/下载 `upx.exe`，有则启用 |
| PyTorch + EasyOCR | **构建后复制**到 `_internal/`，无需用户 pip install |
| ffmpeg | 通过 `--add-data` 打包到 `tools/` |
| 排除项 | 排除 flask/jinja2/torch 等，避免 PyInstaller 分析慢 |
| 输出 | `dist/Video2Shop/` → 自动打包为 `Video2Shop_v{x.y.z}.zip` |

### 构建安装包（Inno Setup）

1. 安装 [Inno Setup](https://jrsoftware.org/isinfo.php)
2. 运行构建脚本生成 `dist/Video2Shop/`
3. 编译安装包：

```batch
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\setup.iss
```

生成 `Video2Shop_Setup_v{x.y.z}.exe`，支持开始菜单快捷方式、桌面图标。

---

## ❓ 常见问题 (FAQ)

<details>
<summary><b>Q: 提示"未找到 Chrome"怎么办？</b></summary>

确认系统已安装 Google Chrome。也可以在设置中切换为 Microsoft Edge 或 Chromium，或选择「自定义路径」手动指定浏览器 exe 位置。
</details>

<details>
<summary><b>Q: 京东加购成功率低？</b></summary>

尝试增大 `add_cart_delay`（例如 1.0 秒）和 `click_retry`（例如 2）。京东页面结构会不定期更新，如持续失败请提 Issue。
</details>

<details>
<summary><b>Q: 视频抽不到文字帧？</b></summary>

降低 `ocr.min_chinese_chars`（例如 10），或减小 `video.frame_interval`（例如 3 秒）。也可以尝试用 `--json` 参数从评论数据提取。
</details>

<details>
<summary><b>Q: 启动时弹出浏览器窗口？</b></summary>

这是「准备工作」功能，程序会自动打开 Chrome 检查京东和 DeepSeek 登录态。如果未登录，在浏览器窗口中扫码登录即可，cookie 会自动保存。可以在设置中关闭「启动时自动检查」。
</details>

<details>
<summary><b>Q: API 和网页版分析有什么区别？</b></summary>

- **API 模式**：使用 DeepSeek V4 Flash 多模态 API 直接上传图片分析，速度快但需要 API Key
- **网页版模式**：通过浏览器上传图片到 chat.deepseek.com，需要登录 DeepSeek 账号，免费使用

在设置页面可以随时切换。
</details>

<details>
<summary><b>Q: DeepSeek 网页版需要登录？</b></summary>

是的。点击「准备工作」按钮，程序会打开浏览器导航到 DeepSeek 聊天页面，在浏览器中扫码或账号登录即可。登录态会保存到 `config/deepseek_auth.json`，后续无需重复登录。

<details>
<summary><b>Q: 首次启动很慢？</b></summary>

首次运行时 EasyOCR 会自动下载中文识别模型（约 100MB）到 `~/.EasyOCR/`，下载完成后后续启动即可秒开。如果网络不畅，可以手动下载模型文件放到该目录。
</details>

<details>
<summary><b>Q: 打包后程序启动报错找不到 ffmpeg？</b></summary>

开发环境请确保 `tools/ffmpeg.exe` 存在（从 https://www.gyan.dev/ffmpeg/builds/ 下载）。打包版本已内置，不需要手动安装。
</details>

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| GUI 框架 | Tkinter + [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) (litera 主题) |
| Web 框架 | Flask + Jinja2 (打包时排除，仅源码运行使用) |
| 浏览器自动化 | [Playwright](https://playwright.dev/) (CDP 模式) |
| AI 分析 | DeepSeek (网页版 + API) |
| OCR | [EasyOCR](https://github.com/JaidedAI/EasyOCR) |
| 视频处理 | OpenCV + ffmpeg (DASH 音视频合并) |
| 打包 | PyInstaller (onedir + UPX) + Inno Setup |
| 配置 | YAML |

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 📮 联系方式

- Issue: [GitHub Issues](../../issues)
- 开发者: [@tingfengsusu](https://github.com/tingfengsusu)
