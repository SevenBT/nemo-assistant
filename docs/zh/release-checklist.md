# 发布检查清单

> [English](../en/release-checklist.md)

在发布 GitHub Release 或附上 Windows 可执行文件之前，请对照本清单检查。

## 源码发布

- 运行 `uv sync --extra dev --frozen`。
- 运行 `uv run python scripts/check_repo.py`。
- 运行 `uv run pytest -q`。
- 确认 `git status --short` 只包含本次发布应有的改动。
- 更新 `CHANGELOG.md`。

## Windows 二进制发布

- 从一个干净或可丢弃的 `dist/` 目录开始。
- 运行 `uv sync --extra build --frozen`。
- 运行 `uv run python -m PyInstaller --clean --noconfirm Nemo_Assistant.spec`。
- 确认 `dist/Nemo Assistant.exe` 已生成。
- 在 Windows 上启动一次可执行文件，确认主窗口能正常打开。
- 确认发布压缩包不包含本地 `config/`、`data/`、`logs/`、缓存、API Key 或笔记。

## 许可证审查

Nemo Assistant 源码采用 MIT 许可证，但二进制发布会打包带有各自许可证的第三方依赖。

发布二进制前：

- 在 Release 说明或压缩包中附上 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和 `DEPENDENCY_LICENSES.md`。
- 从发布环境重新生成完整的依赖许可证清单。
- 审查 PyQt6、pyqt6-fluent-widgets 和 html2text 的 GPL 义务。
- 为已发布的二进制提供对应的源码。

建议的清单生成命令：

```bash
uv run pip-licenses --with-license-file --format=markdown > build/dependency-licenses-full.md
```
