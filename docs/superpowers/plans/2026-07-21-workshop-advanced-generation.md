# 工坊高级生成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先把现有工坊的快速生成从“模型输出直接写入正式工具目录”改造成“暂存、确定性验证、用户确认、原子安装”的可复用治理纵切，为后续接入 Claude Code/Codex 建立可靠边界。

**Architecture:** 在 `app/core/tool_build/` 建立与 UI 无关的工具构建领域层，负责不可变协议对象、临时工作区、manifest 验证、权限/依赖检查、报告和原子安装。现有快速生成只负责调用该服务并展示结果；`ToolRegistry`/`ScriptToolAdapter` 继续负责运行时加载，但新安装必须通过严格协议，历史 manifest 继续兼容加载并标记为 legacy。第一阶段不启动外部编码 Agent，不实现通用 exec、PTY 或 OS 级沙箱。

**Tech Stack:** Python 3.12、PyQt6/qfluentwidgets、pytest、现有 `ToolRegistry`/`ScriptToolAdapter`/`ToolGenerateDialog`、`pathlib`、`ast`、SHA-256 文件摘要；不新增第三方依赖，第一阶段不自动安装生成工具的依赖。

## Global Constraints

- 所有新建函数签名必须使用类型注解，数据对象优先使用 `@dataclass(frozen=True)`。
- 新生成工具必须先进入 `DATA_DIR / "tool_builds" / <build_id> / source`，禁止直接写入 `USER_TOOLS_DIR`。
- 工作目录、cwd 和临时目录不是 Windows 操作系统级沙箱；UI、文档和错误信息不得把静态检查描述为安全保证。
- 第一阶段不启动真实 Claude Code/Codex，不执行生成脚本，不自动安装 manifest 中声明的依赖，不调用真实收费模型作为自动化测试依赖。
- 新安装只接受严格 manifest v1；旧 manifest 继续兼容加载，但必须标记 `legacy/unreviewed`，不能借兼容模式绕过新安装验证。
- `file_read`、`file_write`、`network`、`clipboard_read`、`clipboard_write`、`shell`、`python_subprocess`、`process_spawn` 是有限权限枚举；未声明或超出批准范围的行为必须阻断安装。
- 第一阶段只支持 manifest 指定的工具目录文件和 Python 入口；不把多文件 Agent 构建、依赖安装、自动修复、外部进程管理纳入本阶段。
- 不覆盖用户已有未提交修改，不执行 `git commit` 或 `git push`，除非用户另行明确授权。
- 每个任务必须先写失败测试，再实现最小代码，再运行针对性测试；完成前运行 `uv run python scripts/check_repo.py` 和 `uv run pytest -q`。

---

## 文件结构与职责

### 新建文件

- `app/core/tool_build/__init__.py`：只导出领域层公共类型和 `ToolBuildService`。
- `app/core/tool_build/models.py`：`ToolPermission`、`IssueSeverity`、`ToolManifest`、`ValidationIssue`、`ValidationReport`、`BuildReview`、`InstallResult` 等不可变 DTO。
- `app/core/tool_build/manifest.py`：严格 manifest v1 解析、旧 manifest 兼容解析、参数定义转换和入口/权限/依赖字段校验。
- `app/core/tool_build/workspace.py`：创建 build ID、创建工作区、写入输入和源码、读取源码、计算相对文件摘要、清理工作区。
- `app/core/tool_build/validator.py`：路径边界、JSON/manifest、Python AST、权限、依赖、入口和文件白名单检查。
- `app/core/tool_build/installer.py`：最终重新验证、同名冲突判断、同卷临时目录复制、备份旧版本、原子替换和失败回滚。
- `app/core/tool_build/service.py`：编排暂存、重新验证、用户批准输入和安装；UI 只依赖这个服务。
- `app/ui/tool_build_review_dialog.py`：显示验证报告、声明/检测权限、依赖和阻断问题，收集安装确认。

### 修改文件

- `app/core/config.py:46-58, 357-365`：增加 `TOOL_BUILDS_DIR` 并确保目录存在。
- `app/core/tool_generator.py:77-152, 195-219`：要求模型输出严格 manifest v1 的权限/依赖字段；保留文本解析职责，不在此处写正式目录。
- `app/tools/script_adapter.py:40-80, 239-324`：接入兼容 manifest 解析结果，暴露 `permissions`、`is_legacy_manifest` 和有限依赖状态；不改变旧工具加载行为。
- `app/tools/loader.py:118-160`：拒绝用户工具与内置工具同名的静默覆盖，并保留 legacy 标记。
- `app/tools/registry.py:226-247`：统一拒绝 `enabled=False` 工具执行，覆盖聊天、调度和手动测试入口。
- `app/ui/tool_generate_dialog.py:23-24, 252-300`：移除直接写 `USER_TOOLS_DIR` 的逻辑，改由 `ToolBuildService` 暂存、展示报告和安装。
- `app/ui/toolbox_panel.py:289-345`：在脚本工具详情显示权限、依赖状态和 legacy 标记。
- `app/i18n/zh.py`、`app/i18n/en.py`：增加验证、权限、依赖、legacy、冲突、暂存和安装结果文案。
- `docs/en/security-model.md`、`docs/zh/security-model.md`：补充生成代码不等同于受信任扩展、临时工作区不是沙箱、依赖不自动安装和安装前验证限制。
- `docs/design/workshop-advanced-generation-design.md`：仅在本阶段完成后补充“阶段 1 已实现、外部 Agent 阶段未实现”的状态说明，不把完整设计标记为完成。

### 测试文件

- `tests/test_tool_build_models.py`：DTO、权限集合和状态结果。
- `tests/test_tool_build_manifest.py`：严格/legacy manifest 解析。
- `tests/test_tool_build_workspace.py`：工作区、路径和摘要。
- `tests/test_tool_build_validator.py`：结构、AST、权限、依赖和入口验证。
- `tests/test_tool_build_installer.py`：安装、冲突、回滚和篡改检测。
- `tests/test_tool_build_service.py`：完整暂存到安装流程。
- `tests/test_registry_enabled.py`：禁用工具的统一执行保护。
- `tests/test_tool_generate_dialog.py`：UI 使用假服务验证报告和安装按钮状态。
- 现有 `tests/test_script_adapter_security.py`、`tests/test_read_file_boundary.py`、`tests/test_tool_retry.py`：作为回归测试，不删除或放宽现有断言。

---

## Task 1: 建立工具构建领域模型

**Files:**
- Create: `app/core/tool_build/__init__.py`
- Create: `app/core/tool_build/models.py`
- Test: `tests/test_tool_build_models.py`

**Interfaces:**
- Produces `ToolPermission`, `IssueSeverity`, `BuildStatus`、`ToolManifest`、`ValidationIssue`、`ValidationReport`、`BuildReview`、`InstallResult`，供后续 manifest、validator、installer 和 service 使用。

- [ ] **Step 1: 写失败测试，固定不可变 DTO 和权限行为**

```python
from dataclasses import FrozenInstanceError

import pytest

from app.core.tool_build.models import (
    BuildStatus,
    IssueSeverity,
    ToolPermission,
    ValidationIssue,
    ValidationReport,
)


def test_permission_values_are_stable():
    assert ToolPermission.FILE_READ.value == "file_read"
    assert ToolPermission.PROCESS_SPAWN.value == "process_spawn"


def test_validation_report_is_immutable():
    report = ValidationReport(
        build_id="b1",
        status=BuildStatus.VALIDATING,
        declared_permissions=frozenset(),
        detected_permissions=frozenset(),
        dependencies=(),
        file_hashes={},
        issues=(),
    )

    with pytest.raises(FrozenInstanceError):
        report.status = BuildStatus.INSTALL_REVIEW


def test_validation_report_is_installable_only_without_blocking_issue():
    warning = ValidationIssue("WARN", IssueSeverity.WARNING, "warning")
    blocking = ValidationIssue("BLOCK", IssueSeverity.BLOCK, "blocked")

    assert ValidationReport.is_installable_for((warning,)) is True
    assert ValidationReport.is_installable_for((blocking,)) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_models.py`
Expected: FAIL because `app.core.tool_build` and its DTOs do not exist.

- [ ] **Step 3: 实现最小领域模型**

实现要求：

- 所有 DTO 使用 `@dataclass(frozen=True)`；
- 集合字段使用 `tuple` 或 `frozenset`，不保存可变 list 作为公开状态；
- `BuildStatus` 至少包含 `staged`、`validating`、`validation_failed`、`install_review`、`installed`、`install_failed`、`cancelled`、`abandoned`；
- `ValidationReport.is_installable_for()` 仅在没有 `IssueSeverity.BLOCK` 时返回真；
- `BuildReview` 同时保存 build ID、工具 manifest、脚本文本和验证报告，但不保存环境变量或完整日志；
- `__init__.py` 只导出稳定公共类型，不导入 UI。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_models.py`
Expected: PASS。

- [ ] **Step 5: 运行类型和仓库检查**

Run: `uv run python scripts/check_repo.py`
Expected: PASS；若仓库检查暴露既有问题，只记录，不修改无关文件。

提交：本步骤不自动提交；需要提交时使用 `feat: add tool build domain models`，但必须先取得用户明确授权。

---

## Task 2: 实现严格 manifest v1 和 legacy 兼容解析

**Files:**
- Create: `app/core/tool_build/manifest.py`
- Modify: `app/core/tool_generator.py:77-152, 195-219`
- Test: `tests/test_tool_build_manifest.py`

**Interfaces:**
- Consumes `ToolManifest` and `ToolPermission` from Task 1。
- Produces `parse_manifest_text(text: str, *, mode: Literal["strict", "legacy"]) -> ToolManifest`、`manifest_to_parameters(manifest: ToolManifest) -> dict[str, object]`、`manifest_to_json(manifest: ToolManifest) -> str`。

- [ ] **Step 1: 写失败测试，固定严格协议和兼容行为**

```python
import json

import pytest

from app.core.tool_build.manifest import parse_manifest_text


def valid_manifest(**overrides):
    value = {
        "manifest_version": 1,
        "name": "csv_summary",
        "description": "Summarize CSV data",
        "script": "tool.py",
        "version": "1.0.0",
        "parameters": {"path": {"type": "string", "required": True}},
        "output": {"type": "object"},
        "permissions": ["file_read"],
        "dependencies": [],
    }
    value.update(overrides)
    return value


def test_strict_manifest_requires_version_and_permission_list():
    manifest = parse_manifest_text(json.dumps(valid_manifest()), mode="strict")
    assert manifest.name == "csv_summary"
    assert manifest.permissions == frozenset({"file_read"})


def test_strict_manifest_rejects_unknown_permission():
    with pytest.raises(ValueError, match="unknown permission"):
        parse_manifest_text(json.dumps(valid_manifest(permissions=["magic"])), mode="strict")


def test_strict_manifest_rejects_path_like_dependency():
    with pytest.raises(ValueError, match="dependency"):
        parse_manifest_text(json.dumps(valid_manifest(dependencies=["file:./x"])), mode="strict")


def test_legacy_manifest_parses_without_new_fields_and_is_marked():
    manifest = parse_manifest_text(
        json.dumps({"name": "old", "description": "old", "script": "tool.py"}),
        mode="legacy",
    )
    assert manifest.is_legacy is True
    assert manifest.permissions == frozenset()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_manifest.py`
Expected: FAIL because the strict and legacy parsers do not exist.

- [ ] **Step 3: 实现解析器并收紧生成提示**

实现要求：

- 严格模式只允许 `manifest_version == 1`；
- 工具名只允许 `^[a-zA-Z_][a-zA-Z0-9_]{0,63}$`；
- `script` 必须是相对路径，解析后由 workspace validator 再检查是否在 source 目录；
- 权限只能来自 `ToolPermission`，未知权限直接抛出 `ValueError`；
- 依赖第一阶段只允许空列表；非空依赖解析为阻断问题或在严格安装入口拒绝，不能触发 pip；
- `parameters` 必须是对象，参数类型只允许 `string|number|integer|boolean|array|object`；
- `output` 必须存在且为对象；
- legacy 模式保留当前 `name`、`description`、`script`、`parameters`、`dependencies`、`retry_safe` 等字段兼容性，并设置 `is_legacy=True`；
- `manifest_to_parameters()` 继续过滤 `source == "config"`，并拒绝新 manifest 使用尚未实现的 `source == "manual"`；
- 修改 `_SYSTEM_PROMPT`，要求生成 `manifest_version: 1`、权限枚举和空依赖列表；
- `parse_result()` 仍只负责提取代码块和 JSON，不写文件；严格协议验证由 service 调用。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_manifest.py tests/test_script_adapter_security.py`
Expected: PASS。

- [ ] **Step 5: 回归快速生成解析测试**

Run: `uv run pytest -q tests/test_tool_generator.py`
Expected: PASS；若测试文件不存在，新增最小的 `parse_result()` 回归测试后再运行。

---

## Task 3: 创建隔离的构建工作区和摘要机制

**Files:**
- Modify: `app/core/config.py:46-58, 357-365`
- Create: `app/core/tool_build/workspace.py`
- Test: `tests/test_tool_build_workspace.py`

**Interfaces:**
- Consumes `ToolManifest` from Task 1/2。
- Produces `BuildWorkspace.create(requirement: str, manifest_text: str, script_text: str) -> BuildWorkspace`、`.source_dir`、`.manifest_path`、`.script_path`、`.file_hashes()`、`.read_source()`、`.cleanup()`。

- [ ] **Step 1: 写失败测试，固定目录和路径边界**

```python
from pathlib import Path

import pytest

from app.core.tool_build.workspace import BuildWorkspace


def test_workspace_writes_only_under_tool_builds(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    workspace = BuildWorkspace.create("make a formatter", '{"name":"x"}', "print(1)")

    assert workspace.source_dir.parent.parent == tmp_path / "builds"
    assert workspace.manifest_path.read_text(encoding="utf-8") == '{"name":"x"}'
    assert workspace.script_path.read_text(encoding="utf-8") == "print(1)"
    assert not (tmp_path / "user_tools").exists()


def test_script_path_cannot_escape_source(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    with pytest.raises(ValueError):
        BuildWorkspace.create("req", '{"name":"x","script":"../outside.py"}', "print(1)")


def test_file_hashes_use_relative_paths_and_change_after_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    workspace = BuildWorkspace.create("req", '{"name":"x","script":"tool.py"}', "print(1)")
    first = workspace.file_hashes()
    workspace.script_path.write_text("print(2)", encoding="utf-8")
    assert first["manifest.json"] != workspace.file_hashes()["tool.py"]
    assert all(not Path(name).is_absolute() for name in workspace.file_hashes())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_workspace.py`
Expected: FAIL because `TOOL_BUILDS_DIR` and `BuildWorkspace` do not exist.

- [ ] **Step 3: 实现工作区和配置常量**

实现要求：

- `TOOL_BUILDS_DIR = DATA_DIR / "tool_builds"`，加入 `_ensure_dirs()`；
- build ID 由 `secrets.token_urlsafe()` 或 UUID 生成，不接受用户直接作为路径；
- 工作区结构固定为 `input/`, `source/`, `logs/`, `reports/`；
- 只写入 `input/requirement.txt`、`input/tool-spec.json`、`source/manifest.json`、`source/tool.py`；
- manifest 的 script 解析必须用 `Path.resolve()` + `Path.is_relative_to(source_dir)`；拒绝绝对路径、`..`、指向目录的入口和 source 外的符号链接；
- `file_hashes()` 只递归 source 内普通文件，返回相对 POSIX 路径到 SHA-256；拒绝 symlink、junction/reparse point 和硬链接文件；
- `cleanup()` 只能删除由当前实例创建且路径仍在 `TOOL_BUILDS_DIR` 下的目录，并返回清理结果，不静默吞掉异常；
- 任何写入使用 UTF-8 和原子临时文件替换，避免半写 manifest。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_workspace.py`
Expected: PASS。

- [ ] **Step 5: 运行路径相关回归测试**

Run: `uv run pytest -q tests/test_read_file_boundary.py tests/test_script_adapter_security.py`
Expected: PASS。

---

## Task 4: 实现确定性验证器

**Files:**
- Create: `app/core/tool_build/validator.py`
- Test: `tests/test_tool_build_validator.py`

**Interfaces:**
- Consumes `BuildWorkspace`、`ToolManifest`、`ValidationReport`。
- Produces `validate_workspace(workspace: BuildWorkspace, *, approved_permissions: frozenset[ToolPermission]) -> ValidationReport`。

- [ ] **Step 1: 写失败测试，覆盖阻断性规则**

```python
import json

from app.core.tool_build.models import IssueSeverity, ToolPermission
from app.core.tool_build.validator import validate_workspace
from app.core.tool_build.workspace import BuildWorkspace


def make_workspace(monkeypatch, tmp_path, manifest=None, script="print('ok')"):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    manifest = manifest or {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
    return BuildWorkspace.create("req", json.dumps(manifest), script)


def test_missing_entrypoint_is_blocked(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    workspace.script_path.unlink()
    report = validate_workspace(workspace, approved_permissions=frozenset())
    assert any(issue.code == "ENTRYPOINT_MISSING" for issue in report.issues)
    assert report.is_installable is False


def test_network_call_without_approval_is_blocked(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path, script="import requests\nrequests.get('https://example.com')")
    report = validate_workspace(workspace, approved_permissions=frozenset())
    assert report.detected_permissions == frozenset({ToolPermission.NETWORK})
    assert any(issue.severity is IssueSeverity.BLOCK for issue in report.issues)


def test_dependency_is_blocked_without_running_pip(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 1, "name": "x", "description": "x", "script": "tool.py",
        "parameters": {}, "output": {"type": "object"}, "permissions": [],
        "dependencies": ["requests==2.32.0"],
    }
    workspace = make_workspace(monkeypatch, tmp_path, manifest=manifest)
    report = validate_workspace(workspace, approved_permissions=frozenset())
    assert any(issue.code == "DEPENDENCIES_UNSUPPORTED" for issue in report.issues)


def test_validation_report_does_not_trust_report_file(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    (workspace.reports_dir / "validation.json").write_text('{"installable":true}', encoding="utf-8")
    workspace.script_path.write_text("import os\nos.system('whoami')", encoding="utf-8")
    report = validate_workspace(workspace, approved_permissions=frozenset())
    assert report.is_installable is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_validator.py`
Expected: FAIL because `validate_workspace()` does not exist.

- [ ] **Step 3: 实现结构、路径、AST 和批准范围检查**

实现要求：

- 重新读取 source/manifest.json，不能读取 Agent 自己写入的 validation report 作为结论；
- 校验严格 manifest v1、入口存在、入口在 source 内、入口是普通文件、JSON 和 Python 语法有效；
- AST 检测明显能力：`open` 写模式、`pathlib.Path.write_*`、`requests/httpx/urllib/socket`、`subprocess/os.system/exec`、`clipboard/pyperclip`、`multiprocessing`/进程 API、动态 `eval/exec`、敏感环境变量读取；
- 检测结果是 `frozenset[ToolPermission]`；无法可靠分类的动态调用生成 warning 或 manual-review issue，不得生成“安全通过”结论；
- 检测权限不在 `approved_permissions` 中时产生 `UNAPPROVED_PERMISSION` block；manifest 权限只能是检测权限的上界，不能为 Agent 自己扩大批准范围；
- 当前阶段非空依赖生成 `DEPENDENCIES_UNSUPPORTED` block，绝不调用 `pip`；
- source 内文件仅允许 manifest、入口和后续明确允许的普通文件，拒绝链接、设备文件和 source 外入口；
- 报告记录相对路径、SHA-256、问题代码和脱敏消息，不记录源码、环境变量或完整命令；
- 对源文件大小、AST 复杂度和问题数量设置固定上限，避免验证器被恶意输入拖垮。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_validator.py`
Expected: PASS。

- [ ] **Step 5: 运行安全回归测试**

Run: `uv run pytest -q tests/test_exec_security.py tests/test_script_adapter_security.py tests/test_read_file_boundary.py`
Expected: PASS；发现现有路径工具缺陷时，只在本任务范围内补充 `Path.is_relative_to()` 修复和测试，不重构无关工具。

---

## Task 5: 实现原子安装和旧版本保护

**Files:**
- Create: `app/core/tool_build/installer.py`
- Test: `tests/test_tool_build_installer.py`

**Interfaces:**
- Consumes `BuildWorkspace`、`ValidationReport`、`USER_TOOLS_DIR`。
- Produces `install_verified_build(workspace: BuildWorkspace, report: ValidationReport, *, approved_permissions: frozenset[ToolPermission], overwrite: bool) -> InstallResult`。

- [ ] **Step 1: 写失败测试，覆盖首次安装、冲突和回滚**

```python
import json

import pytest

from app.core.tool_build.installer import install_verified_build
from app.core.tool_build.validator import validate_workspace
from app.core.tool_build.workspace import BuildWorkspace


def test_install_copies_only_verified_source(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    target = tmp_path / "user_tools"
    monkeypatch.setattr("app.core.tool_build.installer.USER_TOOLS_DIR", target)
    workspace = BuildWorkspace.create("req", json.dumps({"manifest_version": 1, "name": "x", "description": "x", "script": "tool.py", "parameters": {}, "output": {"type": "object"}, "permissions": [], "dependencies": []}), "print('{}')")
    report = validate_workspace(workspace, approved_permissions=frozenset())

    result = install_verified_build(
        workspace, report, approved_permissions=frozenset(), overwrite=False
    )

    assert result.installed is True
    assert (target / "x" / "manifest.json").exists()
    assert (target / "x" / "tool.py").exists()


def test_same_name_requires_explicit_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    target = tmp_path / "user_tools"
    target.mkdir()
    (target / "x").mkdir()
    monkeypatch.setattr("app.core.tool_build.installer.USER_TOOLS_DIR", target)
    workspace = BuildWorkspace.create("req", '{"manifest_version":1,"name":"x","description":"x","script":"tool.py","parameters":{},"output":{},"permissions":[],"dependencies":[]}', "print('{}')")
    report = validate_workspace(workspace, approved_permissions=frozenset())

    result = install_verified_build(
        workspace, report, approved_permissions=frozenset(), overwrite=False
    )

    assert result.installed is False
    assert result.reason == "NAME_CONFLICT"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_installer.py`
Expected: FAIL because installer does not exist.

- [ ] **Step 3: 实现最终重验证和原子安装**

实现要求：

- 安装入口先重新读取 workspace 并使用调用方当前明确传入的 `approved_permissions` 重新执行 validator；调用方传入的旧 report 只能作为比较基线，不能作为授权；Task 6 必须显式转发用户当前批准集合；
- 比较安装前文件摘要与 review report，任何变化返回 `STALE_VALIDATION`；
- 目标目录位于 `USER_TOOLS_DIR` 内且 tool name 来自严格 manifest；同名内置工具由 `ToolRegistry`/installer 共同拒绝，不能静默覆盖；
- 首次安装和显式 overwrite 都先复制到 `USER_TOOLS_DIR/.staging/<build_id>`，只复制已验证普通文件；
- overwrite 时把旧用户工具目录移到同卷备份，完成后用 `os.replace()` 替换；失败时恢复旧目录；
- 拒绝 source 内 symlink、junction、hard link 和 source 外入口；
- 返回结构化 `InstallResult`，包含 `installed`、`tool_name`、`reason`、`backup_path`，不暴露完整路径中的敏感信息；
- 第一阶段安装成功后工具仍通过现有 loader 加载，安装器本身不直接修改 Registry。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_installer.py`
Expected: PASS。

- [ ] **Step 5: 运行失败注入测试**

Run: `uv run pytest -q tests/test_tool_build_installer.py -k rollback -vv`
Expected: PASS；旧版本仍存在且新版本目录没有半成品。

---

## Task 6: 接入 ToolBuildService 和 legacy 加载边界

**Files:**
- Create: `app/core/tool_build/service.py`
- Modify: `app/tools/script_adapter.py:40-80, 239-324`
- Modify: `app/tools/loader.py:118-160`
- Test: `tests/test_tool_build_service.py`

**Interfaces:**
- Consumes `parse_manifest_text()`、`BuildWorkspace`、`validate_workspace()`、`install_verified_build()`。
- Produces `ToolBuildService.stage()`、`.review()`、`.install()`；具体签名为：

```python
class ToolBuildService:
    def stage(
        self,
        requirement: str,
        manifest_text: str,
        script_text: str,
    ) -> BuildReview: ...

    def review(self, build_id: str, approved_permissions: frozenset[ToolPermission]) -> BuildReview: ...

    def install(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        overwrite: bool,
    ) -> InstallResult: ...
```

- [ ] **Step 1: 写失败测试，固定 service 生命周期**

```python
def test_stage_never_writes_user_tools(monkeypatch, tmp_path):
    builds = tmp_path / "builds"
    user_tools = tmp_path / "user_tools"
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", builds)
    monkeypatch.setattr("app.core.tool_build.installer.USER_TOOLS_DIR", user_tools)
    service = ToolBuildService()

    review = service.stage("make a safe tool", VALID_MANIFEST, "print('{}')")

    assert review.report.status.value == "staged"
    assert not user_tools.exists()
    assert (builds / review.build_id / "source" / "manifest.json").exists()


def test_install_revalidates_after_script_edit(service, tmp_path):
    review = service.stage("req", VALID_MANIFEST, "print('{}')")
    script = service.workspace_for(review.build_id).script_path
    script.write_text("import os\nos.system('whoami')", encoding="utf-8")

    result = service.install(review.build_id, frozenset(), overwrite=False)

    assert result.installed is False
    assert result.reason == "VALIDATION_FAILED"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_build_service.py`
Expected: FAIL because `ToolBuildService` and workspace lookup do not exist.

- [ ] **Step 3: 实现编排服务并接入 legacy**

实现要求：

- `stage()` 创建工作区、解析严格 manifest、写入输入和 source、立即验证，并返回 `BuildReview`；任何失败都留在 build 目录，不写正式工具目录；
- `review()` 重新读取 workspace，使用用户批准权限生成新报告；
- `install()` 只接受 build ID，重新 review 后调用 installer；禁止 service 接受任意目标路径；
- service 维护 build ID 到 workspace 的安全映射，重启后通过 `TOOL_BUILDS_DIR/<id>` 安全扫描恢复；
- 修改 source 后旧报告失效，安装必须重验；
- `ScriptToolAdapter.from_manifest()` 使用 legacy/strict 解析器，增加只读属性 `permissions` 和 `is_legacy_manifest`；legacy 工具不自动获得新权限；
- `load_user_script_tools()` 在注册前检查同名内置工具，记录 warning 并跳过，修复当前静默覆盖；
- 旧 manifest 继续加载，但不允许通过 service 的严格安装入口产生；
- 不在本任务自动安装依赖，保留现有 legacy 行为并在新安装中阻断依赖。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_tool_build_service.py tests/test_script_adapter_security.py`
Expected: PASS。

- [ ] **Step 5: 运行加载和 registry 回归测试**

Run: `uv run pytest -q tests/test_loader.py tests/test_tool_retry.py`
Expected: PASS；不存在的测试文件需补最小加载回归测试后再运行。

---

## Task 7: 修复禁用工具统一执行边界

**Files:**
- Modify: `app/tools/registry.py:226-247`
- Test: `tests/test_registry_enabled.py`

**Interfaces:**
- Consumes existing `ToolRegistry.execute()` and `BuiltinTool.enabled`。
- Produces a single runtime guarantee: disabled tools return `ToolErrorType.PERMISSION` before parameter casting or tool execution。

- [ ] **Step 1: 写失败测试**

```python
def test_disabled_tool_cannot_execute_even_with_valid_params():
    registry = ToolRegistry()
    tool = _RecordingTool()
    tool.enabled = False
    registry.register(tool)

    result = registry.execute(tool.name, {})

    assert result["status"] == "error"
    assert result["data"]["error_type"] == ToolErrorType.PERMISSION.value
    assert tool.calls == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_registry_enabled.py`
Expected: FAIL because `execute()` currently ignores `tool.enabled`。

- [ ] **Step 3: 在唯一执行入口增加早返回**

在查找工具后、`cast_params()` 前检查 `tool.enabled`，使用 `_make_error(ToolErrorType.PERMISSION, ...)` 返回本地化的禁用信息；不调用参数转换、校验、重试或工具执行。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q tests/test_registry_enabled.py tests/test_tool_retry.py`
Expected: PASS。

- [ ] **Step 5: 验证应用入口不绕过 registry**

Run: `uv run pytest -q tests/test_registry_enabled.py tests/test_scheduler.py tests/test_tool_test_dialog.py`
Expected: PASS；若某入口直接调用 `tool.execute()`，在本任务范围内改为 `registry.execute()`，不新增第二套授权逻辑。

---

## Task 8: 把快速生成 UI 改为报告审核和显式安装

**Files:**
- Create: `app/ui/tool_build_review_dialog.py`
- Modify: `app/ui/tool_generate_dialog.py:23-24, 63-307`
- Modify: `app/ui/toolbox_panel.py:289-345`
- Modify: `app/i18n/zh.py`, `app/i18n/en.py`
- Test: `tests/test_tool_generate_dialog.py`

**Interfaces:**
- Consumes `ToolBuildService.stage/review/install` and `BuildReview`。
- Produces UI behavior:生成完成后显示验证报告；存在阻断问题时安装按钮禁用；用户确认 overwrite 后才调用 service.install；成功后发出现有 `tool_saved(str)` 信号。

- [ ] **Step 1: 写失败 UI 测试，使用假 service**

```python
import pytest

from app.ui.tool_generate_dialog import ToolGenerateDialog


class FakeToolBuildService:
    def __init__(self, review):
        self.review_value = review
        self.install_calls = []

    def stage(self, requirement, manifest_text, script_text):
        return self.review_value

    def install(self, build_id, approved_permissions, *, overwrite):
        self.install_calls.append((build_id, approved_permissions, overwrite))
        return InstallResult(installed=True, tool_name="safe_tool", reason="")


def test_blocking_review_disables_install_button(qtbot, blocking_review):
    dialog = ToolGenerateDialog(registry=ToolRegistry(), build_service=FakeToolBuildService(blocking_review))
    qtbot.addWidget(dialog)
    dialog._show_review(blocking_review)

    assert dialog._install_btn.isEnabled() is False


def test_successful_install_emits_tool_saved(qtbot, installable_review):
    service = FakeToolBuildService(installable_review)
    dialog = ToolGenerateDialog(registry=ToolRegistry(), build_service=service)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.tool_saved):
        dialog._install_review(overwrite=False)
    assert service.install_calls[0][2] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q tests/test_tool_generate_dialog.py`
Expected: FAIL because the dialog has no build service, review view, or install button.

- [ ] **Step 3: 实现 UI 适配，不把验证逻辑放回窗口**

实现要求：

- `ToolGenerateDialog.__init__` 接受可选 `build_service`，默认创建 `ToolBuildService()`；已有调用方不需要知道领域层细节；
- `_on_save()` 只读取编辑器文本并调用 service.stage/review，不再 import `USER_TOOLS_DIR`、`mkdir` 或直接写 manifest/script；
- 新增审核区域或独立 dialog，显示工具名、权限、依赖、检测问题、文件摘要和“安装并启用”；
- 阻断问题存在时禁用安装；警告需要用户明确确认；未确认 overwrite 时不修改目标目录；
- 用户编辑 manifest/script 后清除旧 review，重新调用 stage/review，安装按钮保持禁用直到重新验证；
- 安装成功后发出 `tool_saved(name)`、关闭对话框并让 `ToolboxPanel.refresh()` 重新加载；失败保留构建目录和报告；
- UI 文案说明静态检查不是沙箱，第一阶段不自动安装依赖；
- `ToolboxPanel._DetailPane.load()` 对 ScriptToolAdapter 展示 `permissions` 和 `legacy/unreviewed` 状态，禁止默认展示“安全”。

- [ ] **Step 4: 运行 UI 测试确认通过**

Run: `uv run pytest -q tests/test_tool_generate_dialog.py`
Expected: PASS。

- [ ] **Step 5: 运行现有 UI 回归测试**

Run: `uv run pytest -q -m ui tests/test_toolbox_panel.py tests/test_tool_editor_dialog.py`
Expected: PASS；若文件不存在，运行 `uv run pytest -q -m ui` 并记录收集到的测试。

---

## Task 9: 更新安全文档、验收脚本和完整回归

**Files:**
- Modify: `docs/en/security-model.md`
- Modify: `docs/zh/security-model.md`
- Modify: `docs/design/workshop-advanced-generation-design.md`
- Optional Modify: `docs/design/README.md` only if the design index is missing the approved design link
- Test/verification: all prior tests and repository checks

- [ ] **Step 1: 写文档验收检查**

```python
from pathlib import Path


def test_security_docs_describe_generated_code_boundary():
    for path in (Path("docs/en/security-model.md"), Path("docs/zh/security-model.md")):
        text = path.read_text(encoding="utf-8")
        assert "not a sandbox" in text.lower() or "不是沙箱" in text
        assert "dependency" in text.lower() or "依赖" in text
```

- [ ] **Step 2: 运行测试确认文档现状不满足**

Run: `uv run pytest -q tests/test_security_documentation.py`
Expected: FAIL if the new boundary wording has not been added；若仓库没有该文件，先创建该最小测试。

- [ ] **Step 3: 更新文档和设计状态**

文档必须明确：

- 用户生成代码不是内置受信任代码；
- `cwd`/临时工作区不是 OS 级沙箱；
- 第一阶段不自动安装依赖；
- 新工具必须通过严格 manifest、验证和用户确认安装；
- legacy 工具可以继续加载，但未通过新协议验证；
- 外部 Agent、ProcessRunner、PTY 和 OS 沙箱仍是后续阶段，不应宣称已经交付。

设计文档只增加阶段状态，不修改已批准的产品边界。

- [ ] **Step 4: 运行完整检查**

Run: `uv run python scripts/check_repo.py`
Expected: PASS。

Run: `uv run pytest -q`
Expected: 全部通过，跳过项数量不增加；如果失败，修复实现而不是放宽测试。

Run: `uv run pytest --cov=app --cov-report=term-missing`
Expected: 新增/修改代码覆盖率至少 80%；若全仓库当前基线低于 80%，在结果中区分全仓库基线与本纵切覆盖率，不伪造达标。

- [ ] **Step 5: 运行安全检查**

Run: `uv run python -m compileall -q app`
Expected: PASS。

Run: `uv run pytest -q tests/test_tool_build_* tests/test_registry_enabled.py tests/test_script_adapter_security.py tests/test_read_file_boundary.py`
Expected: PASS。

- [ ] **Step 6: 记录工作树并请求用户审阅**

Run: `git status --short --branch`
Expected: 只显示本功能涉及的新增/修改文件以及会话开始时已有的文档改动；不得覆盖或还原前序工作。

本任务不自动提交。完成后向用户报告测试输出、未实现的外部 Agent/沙箱范围和当前分支名，并等待用户明确授权后再执行 commit/push。

---

## Spec Coverage Review

- **产品范围与快速/高级边界：** Task 8 保留快速生成，Task 9 明确外部 Agent 未在本纵切实现。
- **ToolSpec/manifest/权限：** Tasks 1-2 定义 DTO、严格 manifest 和有限权限；Task 4 校验批准范围。
- **临时工作区与正式目录隔离：** Task 3 创建工作区，Task 5 安装器只接受验证产物。
- **独立验证与不能信任 Agent 报告：** Task 4 和 Task 5 重新读取、重新验证并比较摘要。
- **安装、冲突、回滚：** Task 5 覆盖首次安装、显式覆盖和失败恢复；Task 6 禁止同名内置覆盖。
- **用户干预：** 本阶段不运行外部 Agent；Task 9 明确澄清/恢复属于后续外部 Agent 阶段，避免假装已有交互能力。
- **禁用工具运行时边界：** Task 7 修复 registry 唯一执行入口。
- **测试策略：** Tasks 1-9 分别覆盖模型、协议、路径、验证、安装、集成、UI、安全和回归。
- **后续外部 Agent：** 本计划为后续 `ToolBuilderBackend`/`ProcessRunner` 预留 workspace、manifest、validator、installer 接口，但不提前实现未具备 OS 沙箱或真实后端契约的部分。

## Self-Review

- 已检查计划中的文件路径、接口名称和前后任务依赖，后续任务使用的 `ToolBuildService`、`BuildWorkspace`、`ValidationReport`、`ToolPermission` 名称与前置任务一致。
- 未使用 `TODO`、`TBD`、`Similar to Task N` 或无具体测试的占位步骤。
- 所有改代码任务都先有失败测试、失败命令、实现要求和通过命令。
- 已将“工作目录不是沙箱”“依赖不自动安装”“旧报告不能授权安装”“禁用工具统一拒绝”列为强制约束。
- 未把当前未提交的 `docs/design/current-codebase-improvement-plan.md` 或 `docs/design/README.md` 改动纳入本功能交付，也没有包含系统级效率工具。
