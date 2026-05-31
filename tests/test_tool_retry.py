import unittest

from app.tools.base import BuiltinTool
from app.tools.registry import ToolErrorType, ToolRegistry


class _Tool(BuiltinTool):
    def __init__(
        self,
        outcomes,
        *,
        name="test_tool",
        read_only=True,
        retry_safe=None,
    ):
        self._outcomes = list(outcomes)
        self.calls = 0
        self._name = name
        self._read_only = read_only
        if retry_safe is not None:
            self._retry_safe = retry_safe

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return "test tool"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    @property
    def read_only(self):
        return self._read_only

    def execute(self, params):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _success():
    return {"status": "success", "data": {"ok": True}}


def _error(error_type, retryable=True):
    return {
        "status": "error",
        "data": {
            "message": "temporary failure",
            "error_type": error_type.value,
            "retryable": retryable,
        },
    }


class ToolRetryTests(unittest.TestCase):
    def test_retries_transient_exception_for_read_only_tool(self):
        registry = ToolRegistry()
        tool = _Tool([ConnectionError("temporary"), _success()])
        registry.register(tool)

        result = registry.execute(tool.name, {})

        self.assertEqual(result["status"], "success")
        self.assertEqual(tool.calls, 2)

    def test_retries_standard_error_result_when_retryable(self):
        registry = ToolRegistry()
        tool = _Tool([_error(ToolErrorType.NETWORK), _success()])
        registry.register(tool)

        result = registry.execute(tool.name, {})

        self.assertEqual(result["status"], "success")
        self.assertEqual(tool.calls, 2)

    def test_does_not_retry_non_read_only_tool_by_default(self):
        registry = ToolRegistry()
        tool = _Tool([ConnectionError("temporary"), _success()], read_only=False)
        registry.register(tool)

        result = registry.execute(tool.name, {})

        self.assertEqual(result["status"], "error")
        self.assertEqual(tool.calls, 1)

    def test_retry_safe_allows_non_read_only_tool_retry(self):
        registry = ToolRegistry()
        tool = _Tool(
            [ConnectionError("temporary"), _success()],
            read_only=False,
            retry_safe=True,
        )
        registry.register(tool)

        result = registry.execute(tool.name, {})

        self.assertEqual(result["status"], "success")
        self.assertEqual(tool.calls, 2)

    def test_result_retryable_false_blocks_retry(self):
        registry = ToolRegistry()
        tool = _Tool([_error(ToolErrorType.NETWORK, retryable=False), _success()])
        registry.register(tool)

        result = registry.execute(tool.name, {})

        self.assertEqual(result["status"], "error")
        self.assertEqual(tool.calls, 1)


if __name__ == "__main__":
    unittest.main()
