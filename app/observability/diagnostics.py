"""Allowlisted, local-only diagnostic exports and recursive secret redaction."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

_SECRET = re.compile(r"(?i)(authorization|api.?key|token|password|passwd|secret|credential)")
_USAGE_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "max_tokens"}
_BEARER = re.compile(r"(?i)Bearer\s+[^\s,;\"']+")
_ASSIGN = re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;\"']+")
_PATH = re.compile(r"(?i)(?:[a-z]:[\\/][^\s\"']+|/(?:Users|home)/[^\s\"']+)")


def redact(value, *, key="", changes=None):
    changes = changes if changes is not None else []
    if key not in _USAGE_KEYS and _SECRET.search(key):
        changes.append(key)
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k), changes=changes) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, changes=changes) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact(parsed, changes=changes), ensure_ascii=False)
        cleaned = _PATH.sub("[LOCAL_PATH]", _ASSIGN.sub(r"\1[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value)))
        if cleaned != value:
            changes.append(key or "text")
        return cleaned
    return value


def build_diagnostic(data):
    try:
        app_version = version("nemo-assistant")
    except PackageNotFoundError:
        app_version = None
    # Never export answers, prompts, file/note bodies, arguments, raw errors,
    # session ids or tool results by default. Structured metadata is sufficient
    # for a useful diagnostic without pretending it can reproduce the task.
    allowed = {
        "trace": {"status", "turn_count", "duration_ms", "prompt_tokens", "completion_tokens", "total_tokens", "started_at"},
        "llm_calls": {"seq", "provider", "model", "status", "latency_ms", "ttft_ms", "prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens", "retry_count", "reported_cost_amount", "reported_cost_currency"},
        "tool_calls": {"name", "status", "error_type", "duration_ms"},
        "state_trace": {"seq", "state", "event", "duration_ms"},
        "security_events": {"tool_name", "risk", "decision"},
    }
    output = {"schema_version": 1, "app_version": app_version, "created_at": datetime.now(timezone.utc).isoformat(),
              "replayable": False, "completeness": "metadata_only", "omitted": ["messages", "answers", "arguments", "results", "attachments", "raw_errors", "identifiers"]}
    for name, keys in allowed.items():
        rows = data.get(name, {} if name == "trace" else [])
        output[name] = {k: v for k, v in rows.items() if k in keys} if isinstance(rows, dict) else [{k: v for k, v in row.items() if k in keys} for row in rows]
    changes = []
    output = redact(output, changes=changes)
    output["redacted_fields"] = sorted(set(changes))
    return output
