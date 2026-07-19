# 发布检查清单

> [English](../en/release-checklist.md)

在发布 GitHub Release 或附上 Windows 可执行文件之前，请对照本清单检查。

## 什么时候发布

不按固定日历日期发布。当一组完整的用户可感知改进已经就绪，并且上个版本的已知阻断问题均已解决时发布。

本项目适合累积少量有意义的改进后发布：

- `patch`（`0.1.1`）：向后兼容的错误修复或打包修正。
- `minor`（`0.2.0`）：一组用户可见功能或显著的工作流改进。
- `major`（`1.0.0`）：对稳定兼容性和支持范围作出承诺。

`v0.1.0` 之后的聊天可靠性修复和渲染性能优化已经构成合理的
`v0.2.0` 候选；打包后的可执行文件通过下述 Windows 冒烟检查后即可发布。

## 自动发布流程

1. 从 `main` 创建发布 PR，同时更新 `pyproject.toml`、`uv.lock` 和
   `CHANGELOG.md` 中带日期的版本章节。
2. 常规 `tests` 检查通过后合并 PR。
3. 在合并后的提交上创建并推送附注标签，例如：

   ```bash
   git switch main
   git pull --ff-only
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```

4. `package-windows` 工作流会校验标签和版本元数据、运行仓库检查与测试、
   构建可执行文件、生成包含许可证材料的 ZIP 和 SHA256 文件，并创建
   GitHub **Draft Release**。
5. 从 Draft Release 下载最终产物，完成下方 Windows 和许可证检查，再点击
   **Publish release**。工作流不会自动公开草稿。

工作流仅接受 `vMAJOR.MINOR.PATCH` 格式的稳定版标签。手动运行可用于测试候选包，
但不会创建 Release。失败或已公开的版本不得移动或删除标签，应准备新的 patch 版本。

## 源码发布

- 运行 `uv sync --extra dev --frozen`。
- 运行 `uv run python scripts/check_repo.py`。
- 运行 `uv run python -m pytest -q`。
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
