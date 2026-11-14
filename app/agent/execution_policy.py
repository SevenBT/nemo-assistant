"""Immutable scheduling defaults, separate from permissions and tool retries."""
from __future__ import annotations

from dataclasses import dataclass

from app.agent.contracts import ToolFailureKind, ToolRuntime


@dataclass(frozen=True)
class ExecutionPolicy:
    max_turns: int = 10
    max_workers: int = 4
    max_tool_failures: int = 5

    def __post_init__(self):
        if (any(type(value) is not int for value in (self.max_turns, self.max_workers, self.max_tool_failures))
                or self.max_turns < 0 or self.max_workers < 1 or self.max_tool_failures < 1):
            raise ValueError("Invalid Agent execution limits")

    def partition(self, calls: list[dict], tools: ToolRuntime) -> list[tuple[str, list[dict]]]:
        batches = []
        reads = []
        for call in calls:
            descriptor = tools.describe(call["name"])
            if descriptor is not None and descriptor.read_only:
                reads.append(call)
            else:
                if reads:
                    batches.append(("concurrent", reads))
                    reads = []
                batches.append(("serial", [call]))
        if reads:
            batches.append(("concurrent", reads))
        return batches

    def is_fatal(self, kind: ToolFailureKind) -> bool:
        return kind in (ToolFailureKind.TOOL_NOT_FOUND, ToolFailureKind.PERMISSION)

    def needs_wrap_up(self, turn_count: int) -> bool:
        return turn_count >= self.max_turns


def resolve_policy(max_turns: int | None, policy: ExecutionPolicy | None) -> ExecutionPolicy:
    if policy is not None:
        if max_turns is not None and max_turns != policy.max_turns:
            raise ValueError("max_turns conflicts with ExecutionPolicy.max_turns")
        return policy
    return ExecutionPolicy(max_turns=10 if max_turns is None else max_turns)
