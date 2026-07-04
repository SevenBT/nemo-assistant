# 贡献指南

感谢你对 Nemo Assistant 的关注！本文档说明如何搭建开发环境、运行测试并提交改动。

> 本项目主要在 **Windows** 上开发和运行，部分能力（全局快捷键、划词取词、截图）依赖 Windows 专用库（`keyboard`、`uiautomation`、`pywin32`）。在其他平台上核心逻辑与测试可以运行，但桌面交互功能不保证可用。

## 开发环境

需要 **Python 3.10+**。

```bash
git clone https://github.com/SevenBT/nemo-assistant.git
cd nemo-assistant

# 建议使用虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 安装运行 + 开发依赖（可编辑安装 + dev 分组）
pip install -e ".[dev]"

# 启动应用
python main.py
```

推荐使用 `uv` 复现锁定依赖：

```bash
uv sync --extra dev
uv run python main.py
```

首次启动后，进入 **设置 → API** 添加模型并设为默认。API Key 通过系统 keyring 安全存储，不会写入明文配置。个人配置保存在 `config/app_config.json`（已被 `.gitignore` 忽略，不要提交）。

## 运行测试

测试使用 **pytest**。因为涉及 PyQt 组件，在无显示器环境（含 CI）需要设置离屏平台插件；`litellm` 导入时会联网拉取价格表，用环境变量禁用可加速。

```bash
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
pytest -q

# 或使用 uv
uv run pytest -q

# macOS / Linux (bash)
export QT_QPA_PLATFORM=offscreen
export LITELLM_LOCAL_MODEL_COST_MAP=True
pytest -q
```

查看覆盖率：

```bash
pytest --cov=app --cov-report=term-missing
```

提交 PR 前请确保测试全部通过。新增功能或修复 bug 时，请补充相应测试。

## 代码规范

- 遵循 **PEP 8**，函数签名尽量加类型标注。
- 优先小而聚焦的文件与函数（单文件建议 <800 行，单函数 <50 行）。
- 显式处理错误，不要静默吞掉异常。
- 不要硬编码密钥。密钥一律走 keyring 或环境变量。
- PyQt6 无边框窗口相关的实现约定见 [docs/zh/development-notes.md](docs/zh/development-notes.md)，其中记录了拖动、缩放、主题、FluentWindow 等踩过的坑与正确做法，改动 UI 前建议先读。

## 提交与 PR

- Commit message 使用**英文**，遵循 [Conventional Commits](https://www.conventionalcommits.org/) 格式：
  `feat: ...` / `fix: ...` / `refactor: ...` / `docs: ...` / `test: ...` / `chore: ...`
- 一个 PR 聚焦一件事，描述里说明改了什么、为什么改、怎么验证的。
- 从 `main` 切出功能分支，不要直接推 `main`。

## 报告问题

提 issue 时请附上：操作系统版本、Python 版本、复现步骤，以及 `crash.log`（若有）里的错误栈。
