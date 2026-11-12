"""Strict wire validation shared by protocol codecs."""
import json
import re

from .transport import ProtocolError, ProviderError

MAX_CALLS = 128
MAX_ARGUMENTS = 2 * 1024 * 1024


def object_json(raw):
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError) as exc:
        raise ProtocolError('模型响应包含无效 JSON') from exc
    if not isinstance(value, dict):
        raise ProtocolError('模型响应必须是 JSON 对象')
    return value


def tool_event(call_id, name, arguments, **metadata):
    if not isinstance(call_id, str) or not call_id or len(call_id) > 512:
        raise ProtocolError('模型工具调用缺少有效 ID')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
        raise ProtocolError('模型工具名称无效')
    if isinstance(arguments, str):
        arguments = object_json(arguments)
    if not isinstance(arguments, dict):
        raise ProtocolError('模型工具参数必须是 JSON 对象')
    return dict(type='tool_call', id=call_id, name=name, arguments=arguments, **metadata)


def unique_calls(calls):
    ids = [call['id'] for call in calls]
    if len(set(ids)) != len(ids):
        raise ProtocolError('模型返回了重复的工具调用 ID')
    return calls


def check_error(chunk):
    if chunk.get('error') or chunk.get('type') == 'error':
        raise ProviderError(chunk)


def progress():
    return {'type': 'progress'}
