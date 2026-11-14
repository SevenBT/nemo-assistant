"""Cohere v2 chat events, using the same HTTP pool as other protocols."""
from copy import deepcopy

from .common import MAX_ARGUMENTS, MAX_CALLS, check_error, object_json, progress, tool_event, unique_calls
from .errors import _normalize_usage
from .transport import ProtocolError


def request_body(request):
    messages = deepcopy(request.messages)
    for message in messages:
        message.pop('provider_state', None)
        message.pop('reasoning_content', None)
        for call in message.get('tool_calls', []):
            call.pop('extra_content', None)
    body = dict(model=request.model, messages=messages, stream=True,
                max_tokens=request.max_tokens, temperature=request.temperature, p=request.top_p)
    if request.tools:
        body['tools'] = deepcopy(request.tools)
    return body


def decode(frames):
    started = complete = False
    calls, closed = {}, set()
    has_text, finish, usage = False, None, None
    for event, raw in frames:
        chunk = object_json(raw)
        check_error(chunk)
        kind = chunk.get('type', event)
        if kind == 'message-start':
            if started:
                raise ProtocolError('Cohere 重复开始消息')
            started = True
        elif not started:
            raise ProtocolError('Cohere 缺少消息开始事件')
        elif kind == 'content-delta':
            text = chunk.get('delta', {}).get('message', {}).get('content', {}).get('text')
            if not isinstance(text, str):
                raise ProtocolError('Cohere 文本格式无效')
            if text:
                has_text = True
                yield dict(type='text', delta=text)
        elif kind == 'tool-call-start':
            index = chunk.get('index')
            call = chunk.get('delta', {}).get('message', {}).get('tool_calls')
            if type(index) is not int or not 0 <= index < MAX_CALLS or index in calls or not isinstance(call, dict):
                raise ProtocolError('Cohere 工具起始事件无效')
            calls[index] = deepcopy(call)
            yield progress()
        elif kind == 'tool-call-delta':
            index = chunk.get('index')
            if index not in calls or index in closed:
                raise ProtocolError('Cohere 工具增量顺序无效')
            fn = chunk.get('delta', {}).get('message', {}).get('tool_calls', {}).get('function', {})
            args = fn.get('arguments', '')
            if not isinstance(args, str):
                raise ProtocolError('Cohere 工具参数格式无效')
            target = calls[index].setdefault('function', {})
            target['arguments'] = target.get('arguments', '') + args
            if len(target['arguments']) > MAX_ARGUMENTS:
                raise ProtocolError('Cohere 工具参数超过限制')
            yield progress()
        elif kind == 'tool-call-end':
            index = chunk.get('index')
            if index not in calls or index in closed:
                raise ProtocolError('Cohere 工具结束事件无效')
            closed.add(index)
        elif kind == 'message-end':
            delta = chunk.get('delta') or {}
            finish = delta.get('finish_reason')
            tokens = (delta.get('usage') or {}).get('tokens')
            if tokens is not None:
                usage = _normalize_usage(dict(prompt_tokens=tokens.get('input_tokens'),
                                               completion_tokens=tokens.get('output_tokens')))
                yield dict(type='usage', usage=usage)
            complete = True
            break
        elif kind == 'tool-plan-delta':
            yield progress()
        elif kind not in ('content-start', 'content-end', 'citation-start', 'citation-end'):
            raise ProtocolError('Cohere 返回未知事件')
    if not complete or finish not in ('COMPLETE', 'TOOL_CALL', 'MAX_TOKENS', 'STOP_SEQUENCE') or set(calls) != closed:
        raise ProtocolError('Cohere 响应未完整结束')
    events = unique_calls([tool_event(call.get('id'), call.get('function', {}).get('name'),
                                     call.get('function', {}).get('arguments'))
                           for _, call in sorted(calls.items())])
    if (events and finish != 'TOOL_CALL') or (finish == 'TOOL_CALL' and not events):
        raise ProtocolError('Cohere 工具调用未正常完成，已阻止执行')
    if not events and not has_text:
        raise ProtocolError('Cohere 返回了空回答')
    yield from events
    yield dict(type='done', usage=usage, reasoning_content=None,
               finish_reason='tool_calls' if events else 'stop')
