from pathlib import Path
import re


SECURITY_POLICY_PATHS = (
    Path("docs/en/security-model.md"),
    Path("docs/zh/security-model.md"),
)
EXPECTED_SECURITY_POLICIES = {
    "generated_code_trust": "untrusted_extension",
    "workspace_is_os_sandbox": "false",
    "strict_dependencies_auto_install": "false",
    "strict_generated_code_exec_during_review": "false",
    "strict_manifest_required": "true",
    "strict_manifest_version": "v1",
    "validation_type": "deterministic",
    "validation_scope": "loadability_only",
    "independent_validation_required": "true",
    "capability_ast_analysis": "not_performed",
    "permission_detection_and_approval": "not_performed",
    "manifest_permissions_are": "declarative_metadata",
    "runtime_permission_enforcement": "false",
    "explicit_install_confirmation_required": "true",
    "atomic_move_steps_and_conditional_rollback": "true",
    "disabled_tool_execution_gate": "true",
    "review_ui": "implemented",
    "legacy_review_status": "legacy_unreviewed",
    "windows_path_final_toctou": "not_eliminated",
    "static_analysis_is_safety_proof": "false",
    "external_agent": "not_implemented",
    "user_clarification_resume": "not_implemented",
    "process_runner": "not_implemented",
    "pty": "not_implemented",
    "os_sandbox": "not_implemented",
    "risk_acknowledged_override_install": "not_applicable",
    "blocking_findings_are_overridable": "false",
}
EXPECTED_CAPABILITY_STATUS = {
    "staged_workspace": "implemented",
    "strict_manifest_v1": "implemented",
    "deterministic_validator": "implemented",
    "review_baseline": "implemented",
    "atomic_move_steps_and_conditional_rollback": "implemented",
    "disabled_tool_execution_gate": "implemented",
    "review_ui": "implemented",
    "external_agent": "not_implemented",
    "user_clarification_resume": "not_implemented",
    "process_runner": "not_implemented",
    "pty": "not_implemented",
    "os_sandbox": "not_implemented",
}
POLICY_TABLE_HEADER = "| Policy ID | Value |"
STATUS_TABLE_HEADER = "| Capability ID | Status |"


def _parse_markdown_table(text: str, header: str) -> dict[str, str]:
    lines = text.splitlines()
    header_indexes = [index for index, line in enumerate(lines) if line == header]
    assert len(header_indexes) == 1, f"expected one table headed {header!r}"

    entries: dict[str, str] = {}
    for line in lines[header_indexes[0] + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 2, f"invalid metadata row: {line!r}"
        policy_id, value = cells
        assert policy_id not in entries, f"duplicate metadata ID: {policy_id}"
        entries[policy_id] = value
    return entries


def _contains_any(text: str, concepts: tuple[str, ...]) -> bool:
    normalized_text = text.lower()
    return any(concept.lower() in normalized_text for concept in concepts)


def test_security_docs_describe_generated_code_boundary() -> None:
    boundary_concepts = (
        ("built-in trusted code", "内置受信任代码"),
        ("automatically install", "自动安装"),
        ("strict manifest v1", "严格 manifest v1"),
        ("deterministic validation", "确定性验证"),
        ("declarative metadata", "声明性元数据"),
        ("disabled-tool execution gate", "禁用工具执行门禁"),
        ("review UI", "审核 UI"),
        ("final TOCTOU", "最终 TOCTOU"),
        ("not a proof of safety", "不是安全证明"),
    )
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        missing_concepts = [
            concepts
            for concepts in boundary_concepts
            if not _contains_any(text, concepts)
        ]
        assert not missing_concepts, f"{path} is missing: {missing_concepts}"


def test_security_docs_describe_workspace_is_not_a_sandbox() -> None:
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        assert _contains_any(text, ("not OS-level sandboxes", "不是操作系统级沙箱"))
        assert _contains_any(
            text,
            (
                "does not limit a process's operating-system permissions",
                "不会限制进程实际拥有的操作系统权限",
            ),
        )


def test_security_docs_describe_strict_new_tool_installation_requirements() -> None:
    requirements = (
        ("does not automatically install strict-tool dependencies", "不自动安装 strict 工具依赖"),
        ("strict manifest v1", "严格 manifest v1"),
        ("independent validation", "独立验证"),
        ("does NOT perform capability or permission analysis", "能力或权限分析"),
        ("independently revalidated artifact", "重新独立验证的产物"),
    )
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        missing_requirements = [
            concepts for concepts in requirements if not _contains_any(text, concepts)
        ]
        assert not missing_requirements, f"{path} is missing: {missing_requirements}"


def test_security_docs_describe_legacy_first_execution_risk() -> None:
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        assert _contains_any(text, ("legacy/unreviewed",))
        assert _contains_any(text, ("first explicit execution", "第一次显式执行"))
        assert _contains_any(text, ("network access", "网络访问"))
        assert _contains_any(text, ("package build code", "包构建代码"))


def test_security_docs_describe_conditional_rollback_boundary() -> None:
    boundary_concepts = (
        ("atomic no-clobber move or replacement steps", "原子 no-clobber 移动或替换步骤"),
        ("overwrite is a multi-step process", "覆盖是多步骤流程"),
        ("root, endpoint, and backup identities", "root、endpoint 和 backup identity"),
        ("fail closed",),
        ("preserve the evidence", "保留现场"),
        ("does not guarantee a kernel-level transaction", "不保证内核级事务"),
        ("does not guarantee recovery", "不保证内核级事务或必然恢复"),
    )
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        missing_concepts = [
            concepts
            for concepts in boundary_concepts
            if not _contains_any(text, concepts)
        ]
        assert not missing_concepts, f"{path} is missing: {missing_concepts}"


def test_security_policy_metadata_requires_expected_policies_and_matches_in_both_languages() -> None:
    parsed_policies = [
        _parse_markdown_table(path.read_text(encoding="utf-8"), POLICY_TABLE_HEADER)
        for path in SECURITY_POLICY_PATHS
    ]

    assert EXPECTED_SECURITY_POLICIES.items() <= parsed_policies[0].items()
    assert EXPECTED_SECURITY_POLICIES.items() <= parsed_policies[1].items()
    assert parsed_policies[0] == parsed_policies[1]


def test_security_docs_describe_no_override_fix_and_revalidate_boundary() -> None:
    boundary_concepts = (
        ("not user-overridable", "不可由用户覆盖"),
        ("could not load or run", "无法加载或运行"),
        ("fix the source and re-validate", "修复源码并重新验证"),
        ("judge for themselves", "自行判断"),
        ("not a proof of safety", "不是安全证明"),
    )
    for path in SECURITY_POLICY_PATHS:
        text = path.read_text(encoding="utf-8")

        missing_concepts = [
            concepts
            for concepts in boundary_concepts
            if not _contains_any(text, concepts)
        ]
        assert not missing_concepts, f"{path} is missing: {missing_concepts}"


def test_advanced_generation_design_has_one_phase_one_status_id() -> None:
    text = Path("docs/design/workshop-advanced-generation-design.md").read_text(
        encoding="utf-8"
    )
    status_ids = re.findall(r"^- Status-ID: ([a-z0-9_]+)$", text, flags=re.MULTILINE)

    assert status_ids == ["phase_1_implemented"]


def test_advanced_generation_design_status_controls_delivery_reading() -> None:
    text = Path("docs/design/workshop-advanced-generation-design.md").read_text(
        encoding="utf-8"
    )

    assert "正文描述完整目标态/未来设计" in text
    assert "只有阶段状态表标为 `implemented` 的能力才已交付" in text
    assert "现在时产品描述不代表当前实现" in text
    assert "阶段 1 当前已实现" in text
    assert "暂存工作区" in text
    assert "严格 manifest v1" in text
    assert "确定性验证器" in text
    assert "审核 UI" in text
    assert "外部 Claude Code/Codex Agent" in text
    assert "自动修复" in text
    assert "多文件 Agent" in text
    assert "Windows path API" in text
    assert "最终 TOCTOU" in text
    assert "静态分析" in text
    assert "完整高级生成设计尚未实施" in text
    assert "外部 Claude Code/Codex Agent" in text
    assert "仍未实现" in text
    assert "原子 no-clobber 移动或替换步骤" in text
    assert "覆盖是多步骤流程" in text
    assert "fail closed" in text
    assert "不保证内核级事务或必然恢复" in text

    statuses = _parse_markdown_table(text, STATUS_TABLE_HEADER)

    assert EXPECTED_CAPABILITY_STATUS.items() <= statuses.items()
