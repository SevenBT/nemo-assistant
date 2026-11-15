"""Offline wiring example: python -m scripts.agent_headless (no desktop services)."""
from __future__ import annotations

import json

from app.agent.agent import Agent
from app.agent.agent_context import AgentContext
from app.agent.contracts import ToolDescriptor, ToolExecutionContext, ToolResult


class DemoModel:
    def chat_stream(self, messages, tools=None, **kwargs):
        yield {"type": "text", "delta": "Agent core ran without desktop services."}
        yield {"type": "done"}


class NoTools:
    def definitions(self) -> list[dict]:
        return []

    def describe(self, name: str) -> ToolDescriptor | None:
        return None

    def execute(self, name: str, arguments: dict, context: ToolExecutionContext) -> ToolResult:
        return {
            "status": "error",
            "data": {"error_type": "tool_not_found", "message": f"Unknown tool: {name}"},
        }

    def format_result(self, result: ToolResult) -> str:
        return json.dumps(result, ensure_ascii=False)


def main() -> int:
    result = Agent(
        AgentContext(llm_gateway=DemoModel(), registry=NoTools()),
        [{"role": "user", "content": "Run the offline example."}],
    ).run_sync()
    print(result["answer"] if result["ok"] else result["error"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
