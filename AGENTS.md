# Nemo Assistant 项目协作规范

适用于本仓库中的 AI 编码代理。公开贡献指南见 `CONTRIBUTING.md`，开发与发布文档见 `docs/`。执行时以用户当前明确要求为准。

## 沟通

- 默认使用中文与维护者沟通，简洁说明结果、依据、验证和未完成项。
- 修改前先阅读相关实现；不要把设计文档中的计划能力当成当前已实现能力。
- 不把模拟客户端测试通过表述为真实模型质量或服务商联通验证通过。

## Git 与分支

- 开始修改前，先运行 `git branch --show-current` 和 `git status --short`，确认所在分支及已有改动。
- **不得直接在 `main` / `master` 上修改或提交任务代码。** 新的独立任务从最新可用的 `main` 创建 `codex/<任务名>` 分支，再开始修改；用户指定分支时遵从用户要求。
- 继续同一个任务时沿用它已有的工作分支，不重新切回主分支。
- 若发现任务改动已经发生在主分支，先完整保留改动，将本次任务保存到工作分支，再验证主分支恢复到原提交且工作区干净，最终切回工作分支。
- 保留用户已有的修改和暂存状态，不使用整体重置、清理或覆盖操作丢弃其他工作。
- 提交保持聚焦，英文提交信息使用 Conventional Commits，例如 `feat(eval): ...`、`fix: ...`、`docs: ...`。

## 开发与依赖

- Python 最低版本与依赖以 `pyproject.toml`、锁文件为准；当前要求 Python 3.12+。
- 桌面开发使用 `uv sync --extra desktop --extra dev --frozen`；独立评估使用 `uv sync --project evals --extra dev --frozen`。
- 优先沿用现有 PyQt6 / qfluentwidgets 模式，不为局部改动另起一套架构。
- 修改无边框窗口、划词、截图、主题或嵌入对话框前，先阅读 [桌面开发说明](docs/en/development-notes.md)。
- 修改工具、文件权限、Shell/Python 执行、剪贴板、网页抓取、运行记录、笔记、记忆或调度前，先阅读 [安全模型](docs/en/security-model.md)。
- 保持生产 Agent 和评估工具的依赖方向：应用不导入 `nemo_eval`；评估内核通过 `adapters/` 接入应用。独立评估不读取个人桌面配置、keyring 或用户数据库。

## 验证

按实际改动范围选择检查；文档调整运行仓库检查，代码变更运行相关测试，发布前完成发布清单要求的完整验证。明确区分已运行、未运行和失败项。

```powershell
# 仓库一致性检查：使用桌面依赖环境，包含打包导入检查。
uv run --extra desktop --extra dev --frozen python scripts/check_repo.py

# 桌面应用测试；无显示环境按需设置 QT_QPA_PLATFORM=offscreen。
uv run --extra desktop --extra dev --frozen pytest -q

# 评估器自动化测试，包含生产 Agent 离线场景，不调用真实模型。
uv run --project evals --extra dev --frozen pytest evals/tests -q
```

真实模型评估入口为 `uv run --project evals --frozen nemo-eval evaluate`。它会产生模型费用，在任务需要真实评估且配置就绪时执行。使用方法见 [维护者评估指南](docs/zh/agent-evaluation.md)。默认 CI 通过 pytest 运行自动化测试；真实评估和 Judge 使用显式配置，结果供维护者决定是否发布。新增功能或修复缺陷时，按行为风险补充或更新相关自动化测试，并运行适当的检查；不为增加数量编写重复测试。

## 数据与发布

- 密钥使用环境变量或系统 keyring，不写入源码、文档、提交和日志。
- 本地 `config/`、`data/`、日志、缓存、构建输出和 `artifacts/` 不提交。
- `evals/configs/live.toml`、`evals/configs/judge.toml` 是本地配置，不提交；可复用示例使用 `.example.toml`。
- 发布二进制前阅读 [发布检查清单](docs/zh/release-checklist.md)，保留许可证材料并验证最终 Windows 产物。
