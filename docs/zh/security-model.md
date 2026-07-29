# 安全模型

> [English](../en/security-model.md)

Nemo Assistant 以本地优先为原则，但它仍可在用户机器上执行有能力的操作。本文档描述面向贡献者与维护者的预期安全边界。

## 信任边界

- 用户的笔记、记忆、会话、trace、截图和配置都保存在本地 `data/` 和 `config/` 目录下。
- 服务商 API Key 与搜索 API Key 通过操作系统 keyring 存储。
- 内置工具运行在本地桌面应用进程内，除非某个工具显式创建了子进程。
- 已有的用户添加工具仍可作为兼容的本地扩展加载，但用户生成的代码不是内置受信任代码，不能仅因其位于本机就被信任。

## 生成工具构建边界

用户生成的代码不是内置受信任代码。`cwd` 和暂存工作区不是操作系统级沙箱；使用这些目录不会限制进程实际拥有的操作系统权限。

阶段 1 不自动安装 strict 工具依赖，也不执行生成代码。新工具必须提供严格 manifest v1 并在安装前通过确定性独立验证。验证只检查"可加载性"——manifest 结构与 strict v1 合规、存在且语法正确的 Python 入口、受允许且有界的源码树，以及阶段 1 要求依赖为空这一约束。验证**不做**能力或权限分析：manifest 的 `permissions` 只作为声明性元数据记录，不会被独立检测、交叉核对或由用户单独批准，运行时执行也不据此强制限制。验证、审核和安装路径不会执行生成代码。安装器只接受重新独立验证的产物，除非显式请求覆盖，否则会拒绝冲突。首次安装使用原子 no-clobber 移动或替换步骤；覆盖是多步骤流程。仅当 root、endpoint 和 backup identity 与目标状态仍可安全验证时才执行回滚；否则 fail closed 并保留现场。这不保证内核级事务或必然恢复。禁用工具执行门禁会在任何运行时校验、重试或执行之前拒绝已禁用的工具。审核 UI 展示"是否可安装"的状态和任何阻断问题，并可查看与编辑产物。运行时执行仍不处于操作系统级沙箱内。

每个阻断发现都意味着工具当前无法加载或运行（manifest 缺失或无效、Python 语法无效、入口损坏或类型错误、声明了依赖，或源码树无法在有界范围内被安全读取）。阻断发现不可由用户覆盖：用户必须修复源码并重新验证。由于安装不再对所请求的能力设门禁，用户须自行判断是否安装并启用某个生成工具。静态验证不是安全证明，不分析行为，工具也不在沙箱中运行——验证通过只表示工具格式正确、可加载，并不表示它安全。

legacy 工具可以继续加载以保持兼容，但它们属于 legacy/unreviewed：未通过严格 manifest v1 和确定性验证协议，不能借助兼容加载满足新工具安装要求。它们历史上的 legacy 执行路径仍可能在第一次显式执行时自动安装缺失依赖；该过程可能使用网络访问和包构建代码。执行前应审核 legacy manifest 及其依赖。

确定性验证只对既定协议做有界结构与语法检查（manifest、入口 Python 语法、源码树边界），不做能力或行为的 AST 分析。它不是安全证明、完整行为分析或操作系统级沙箱。Windows path API 可降低路径边界暴露，但仅靠静态验证和文件系统检查无法消除最终 TOCTOU 窗口。

外部 Claude Code/Codex Agent、ProcessRunner、PTY/ConPTY、自动修复循环、多文件 Agent 执行和操作系统级沙箱尚未交付，阶段 1 不包含这些能力。用户澄清后恢复同样属于后续工作。不能把它们描述为当前已经提供的保护或能力，完整高级生成设计也尚未完成。

## 策略元数据

以下稳定元数据与上文的可读安全边界一致，但不替代这些说明。

| Policy ID | Value |
| --- | --- |
| generated_code_trust | untrusted_extension |
| workspace_is_os_sandbox | false |
| strict_dependencies_auto_install | false |
| strict_generated_code_exec_during_review | false |
| strict_manifest_required | true |
| strict_manifest_version | v1 |
| validation_type | deterministic |
| validation_scope | loadability_only |
| independent_validation_required | true |
| capability_ast_analysis | not_performed |
| permission_detection_and_approval | not_performed |
| manifest_permissions_are | declarative_metadata |
| runtime_permission_enforcement | false |
| explicit_install_confirmation_required | true |
| atomic_move_steps_and_conditional_rollback | true |
| disabled_tool_execution_gate | true |
| review_ui | implemented |
| legacy_review_status | legacy_unreviewed |
| windows_path_final_toctou | not_eliminated |
| static_analysis_is_safety_proof | false |
| external_agent | not_implemented |
| user_clarification_resume | not_implemented |
| process_runner | not_implemented |
| pty | not_implemented |
| os_sandbox | not_implemented |
| risk_acknowledged_override_install | not_applicable |
| blocking_findings_are_overridable | false |

## 危险能力

以下几类工具需要格外小心：

- 文件读取与写入。
- Shell 命令执行。
- Python 代码执行。
- 剪贴板读／写。
- 网页抓取与搜索。
- 定时任务与提醒。
- 笔记与记忆的变更。

高风险工具在示例配置中应默认保持关闭，除非用户显式启用。

## 当前默认值

`config/app_config.example.json` 默认关闭风险最高的工具状态：

- `exec`
- `run_python`
- `save_file`

需要 API Key 的搜索服务商会把 Key 存入 keyring；若配置的 Key 缺失，网页搜索会回退到 DuckDuckGo。

## 贡献者检查清单

新增或修改工具时：

- 通过共享的辅助函数校验文件路径，而不是手写字符串检查。
- 用显式超时约束网络请求。
- 从 trace 和日志中脱敏 Key、token、密码和 authorization 请求头。
- 避免把父进程的完整环境变量传给子进程工具。
- 尽量使用只读工具；在工具描述中清晰标注会产生变更的操作。
- 在相关时，为路径遍历、SSRF、命令执行和密钥脱敏补充测试。

## 发布检查清单

发布二进制之前：

- 运行测试套件。
- 运行 `python scripts/check_repo.py`。
- 从干净的 `dist/` 目录执行一次 PyInstaller 打包。
- 审查打包的依赖许可证。
- 检查打包产物不包含本地 `config/`、`data/`、日志、缓存或 API Key。
