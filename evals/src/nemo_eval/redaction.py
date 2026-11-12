"""Sanitize the explicit evidence subset sent to an external Judge."""
import re
import json

_KEY = re.compile(r"(?i)^(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|credential)$")
_BEARER = re.compile(r"(?i)Bearer\s+[^\s,;\"']+")
_ASSIGN = re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*)[^\s,;\"'&]+")
_PATH = re.compile(r"(?i)(?:[a-z]:[\\/][^\s\"']+|/(?:Users|home)/[^\s\"']+)")


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _KEY.fullmatch(str(k)) else sanitize(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(sanitize(parsed, secrets), ensure_ascii=False)
        return _PATH.sub("[LOCAL_PATH]", _ASSIGN.sub(r"\1[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value)))
    return value
