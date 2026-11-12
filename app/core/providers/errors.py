from __future__ import annotations
import json, re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

_MAX_RETRY_AFTER_SECONDS = 30.0
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|credential)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|credential)\b\s*[:=]\s*([^\s,;]+)"
)
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|credential)=)[^&#\s]+"
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:[\\/](?:[^\s,;\"']+[\\/])*[^\s,;\"']+|/(?:Users|home|tmp|var|private)/[^\s,;\"']+)"
)


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _read_response_payload(response: Any) -> Any:
    response_json = _safe_getattr(response, "json")
    if callable(response_json):
        try:
            return response_json()
        except Exception:
            pass

    response_read = _safe_getattr(response, "read")
    if callable(response_read):
        try:
            response_read()
        except Exception:
            pass

    if callable(response_json):
        try:
            return response_json()
        except Exception:
            pass

    text = _safe_getattr(response, "text")
    if text:
        return text
    return None


def _get_error_payload(exc: Exception) -> Any:
    payload = _safe_getattr(exc, "body") or _safe_getattr(exc, "doc")
    if payload is not None:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except ValueError:
                pass
        return payload

    response = _safe_getattr(exc, "response")
    if response is None:
        return None

    return _read_response_payload(response)


def _error_type_code(payload: Any) -> tuple[str | None, str | None]:
    data: dict[str, Any] | None = None
    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, str) and payload.strip():
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    if not isinstance(data, dict):
        return None, None

    err = data.get("error")
    err_type = data.get("type")
    err_code = data.get("code")
    if isinstance(err, dict):
        err_type = err.get("type") or err_type
        err_code = err.get("code") or err_code
    return (
        str(err_type).strip().lower() if err_type else None,
        str(err_code).strip().lower() if err_code else None,
    )


def _retry_after_from_headers(headers: Any) -> float | None:
    if not headers:
        return None

    def header_value(name: str) -> Any:
        if hasattr(headers, "get"):
            value = headers.get(name) or headers.get(name.title())
            if value is not None:
                return value
        if isinstance(headers, dict):
            for key, value in headers.items():
                if isinstance(key, str) and key.lower() == name.lower():
                    return value
        return None

    try:
        retry_ms = header_value("retry-after-ms")
        if retry_ms is not None:
            value = float(retry_ms) / 1000.0
            if value > 0:
                return value
    except (TypeError, ValueError):
        pass

    retry_after = header_value("retry-after")
    if retry_after is None:
        return None
    text = str(retry_after).strip()
    if not text:
        return None
    try:
        return max(0.1, float(text))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(text)
    except Exception:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.1, (retry_at - datetime.now(retry_at.tzinfo)).total_seconds())


# "目标计算机积极拒绝" / connection refused：目标端口拒绝握手，通常是本地代理
# 未启动或 base_url 端口错配。重试毫无意义（每次都撞同一堵墙），单独归类且不重试。
_CONNECTION_REFUSED_MARKERS = (
    "winerror 10061",
    "econnrefused",
    "connection refused",
    "actively refused",
    "由于目标计算机积极拒绝",
)


def _looks_like_connection_refused(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CONNECTION_REFUSED_MARKERS)


def _sanitize_sensitive_value(value: Any, *, key: str = "") -> Any:
    """Recursively redact provider data before it reaches UI or persistence."""

    if key and _SENSITIVE_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_sensitive_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_sensitive_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_error_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_error_text(str(value))


def _sanitize_error_text(text: str) -> str:
    sanitized = _BEARER_RE.sub("Bearer [REDACTED]", text)
    sanitized = _ASSIGNMENT_SECRET_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", sanitized
    )
    sanitized = _QUERY_SECRET_RE.sub(
        lambda match: f"{match.group(1)}[REDACTED]", sanitized
    )
    sanitized = _ABSOLUTE_PATH_RE.sub("[PATH]", sanitized)
    return sanitized[:500]


def _safe_error_message(payload: Any, exc: Exception) -> str:
    sanitized_payload = _sanitize_sensitive_value(payload)
    if isinstance(sanitized_payload, dict):
        error = sanitized_payload.get("error")
        if isinstance(error, dict):
            candidate = error.get("message")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        candidate = sanitized_payload.get("message")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    if isinstance(sanitized_payload, str) and sanitized_payload.strip():
        return sanitized_payload.strip()
    return _sanitize_error_text(str(exc)).strip()


def sanitize_error_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return an immutable-style sanitized event copy for UI/log/trace use."""

    safe = {
        key: _sanitize_sensitive_value(value, key=key)
        for key, value in event.items()
        if key in {
            "type",
            "message",
            "status_code",
            "error_kind",
            "error_type",
            "error_code",
            "retry_after",
        }
    }
    safe["type"] = "error"
    safe["message"] = _sanitize_error_text(str(safe.get("message") or "Provider request failed"))
    return safe


def _error_event(exc: Exception, prefix: str = "") -> dict:
    """把 SDK/httpx 异常转换为网关可判断的结构化 error 事件。"""
    response = getattr(exc, "response", None)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    payload = _get_error_payload(exc)
    err_type, err_code = _error_type_code(payload)
    headers = getattr(response, "headers", None)

    raw_message = _safe_error_message(payload, exc)
    message = raw_message

    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        error_kind = "timeout"
    elif "connection" in name:
        error_kind = "connection"
    else:
        error_kind = None
    # Gateways may wrap connection-refused failures in generic server errors.
    if _looks_like_connection_refused(f"{message} {str(exc)}"):
        error_kind = "connection_refused"
    if prefix:
        message = f"{prefix}: {message}"

    return sanitize_error_event({
        "type": "error",
        "message": message,
        "status_code": int(status_code) if status_code is not None else None,
        "error_kind": error_kind,
        "error_type": err_type,
        "error_code": err_code,
        "retry_after": _retry_after_from_headers(headers),
    })


def _field(data: Any, name: str, default: Any = None) -> Any:
    """Read a field from either SDK objects or plain response dictionaries."""
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


def _coerce_int(value: Any) -> int | None:
    """宽容地把 usage 字段转 int；非数值返回 None，不让脏数据中断记录。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_usage(usage: Any) -> dict[str, int] | None:
    """把 SDK usage 对象或 dict 归一为 token 统计字典（OpenAI 形状）。

    兼容流式最后一帧的 usage：prompt/completion/total_tokens，以及
    prompt_tokens_details.cached_tokens（缓存命中，provider 可选）。
    任何字段缺失或非数值都安全跳过。
    """
    if usage is None:
        return None
    prompt = _coerce_int(_field(usage, "prompt_tokens"))
    completion = _coerce_int(_field(usage, "completion_tokens"))
    total = _coerce_int(_field(usage, "total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    cached = None
    details = _field(usage, "prompt_tokens_details")
    if details is not None:
        cached = _coerce_int(_field(details, "cached_tokens"))
    if cached is None:
        cached = _coerce_int(_field(usage, "prompt_cache_hit_tokens"))
    if cached is None:
        # 部分网关直接平铺 cached_tokens。
        cached = _coerce_int(_field(usage, "cached_tokens"))

    if prompt is None and completion is None and total is None and cached is None:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
    }
