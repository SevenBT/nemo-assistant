from app.tools.base import BuiltinTool
from app.tools.registry import ToolErrorType, ToolRegistry


class _RecordingTool(BuiltinTool):
    def __init__(self, name: str = "recording_tool", *, rejects_pipeline: bool = True):
        self._name = name
        self._rejects_pipeline = rejects_pipeline
        self.calls = 0
        self.cast_calls = 0
        self.validate_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Records all execution pipeline calls."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def cast_params(self, params: dict) -> dict:
        self.cast_calls += 1
        if self._rejects_pipeline:
            raise AssertionError("Disabled tools must not cast parameters")
        return params

    def validate_params(self, params: dict) -> list[str]:
        self.validate_calls += 1
        if self._rejects_pipeline:
            raise AssertionError("Disabled tools must not validate parameters")
        return []

    def execute(self, params: dict) -> dict:
        self.calls += 1
        return {"status": "success", "data": {}}


def test_disabled_tool_returns_permission_before_execution_pipeline():
    registry = ToolRegistry()
    tool = _RecordingTool()
    tool.enabled = False
    registry.register(tool)

    result = registry.execute(tool.name, {})

    assert result["status"] == "error"
    assert result["data"]["error_type"] == ToolErrorType.PERMISSION.value
    assert result["data"]["retryable"] is False
    assert tool.cast_calls == 0
    assert tool.validate_calls == 0
    assert tool.calls == 0


def test_registry_exposes_and_applies_enabled_tool_states():
    registry = ToolRegistry()
    enabled_tool = _RecordingTool("enabled_tool")
    disabled_tool = _RecordingTool("disabled_tool")
    registry.register(enabled_tool)
    registry.register(disabled_tool)

    registry.apply_saved_states({disabled_tool.name: False})
    seeded_states = registry.seed_default_off(
        frozenset((enabled_tool.name, "unregistered")),
        {disabled_tool.name: False},
    )

    assert registry.get(enabled_tool.name) is enabled_tool
    assert registry.get_all() == [enabled_tool, disabled_tool]
    assert registry.get_enabled() == [enabled_tool]
    assert registry.get_openai_functions() == [enabled_tool.to_openai_function()]
    assert registry.tool_names == [enabled_tool.name, disabled_tool.name]
    assert seeded_states == {disabled_tool.name: False, enabled_tool.name: False}


def test_registry_returns_not_found_error_for_unknown_tool():
    result = ToolRegistry().execute("missing", {})

    assert result["status"] == "error"
    assert result["data"]["error_type"] == ToolErrorType.TOOL_NOT_FOUND.value
    assert result["data"]["retryable"] is False


def test_registry_normalizes_scalar_tool_output():
    class _ScalarTool(_RecordingTool):
        def execute(self, params: dict) -> str:
            self.calls += 1
            return "result"

    registry = ToolRegistry()
    tool = _ScalarTool(rejects_pipeline=False)
    registry.register(tool)

    result = registry.execute(tool.name, {})

    assert result == {"status": "success", "data": {"result": "result"}}
    assert tool.calls == 1


def test_format_result_adds_permission_hint_and_truncates_long_content():
    permission_result = {
        "status": "error",
        "data": {
            "message": "denied",
            "error_type": ToolErrorType.PERMISSION.value,
        },
    }
    long_result = {"status": "success", "data": {"message": "x" * 8_100}}

    formatted_permission = ToolRegistry.format_result(permission_result)
    formatted_long = ToolRegistry.format_result(long_result)

    assert "permission" in formatted_permission.lower()
    assert "Result truncated" in formatted_long
