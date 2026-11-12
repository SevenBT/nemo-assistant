"""OpenAI-compatible Chat Completions wire codec, without SDK objects."""
from copy import deepcopy

from .common import (MAX_ARGUMENTS, MAX_CALLS, check_error, object_json,
                     progress, tool_event, unique_calls)
from .errors import _normalize_usage
from .transport import ProtocolError


def request_body(request):
    messages = deepcopy(request.messages)
    for message in messages:
        message.pop('provider_state', None)
        if request.provider not in ('deepseek', 'dashscope', 'zai'):
            message.pop('reasoning_content', None)
        if request.provider != 'gemini':
            for call in message.get('tool_calls', []):
                call.pop('extra_content', None)
    body = dict(model=request.model, messages=messages, stream=True,
                stream_options={'include_usage': True})
    # Reasoning models reject sampling controls and use a different limit field.
    reasoning = request.provider == 'openai' and request.model.startswith(('o1', 'o3', 'o4', 'gpt-5'))
    body['max_completion_tokens' if reasoning else 'max_tokens'] = request.max_tokens
    if not reasoning:
        body.update(temperature=request.temperature, top_p=request.top_p)
    if request.provider == 'deepseek':
        body['thinking'] = {'type': 'disabled'}
    if request.tools:
        body.update(tools=request.tools, tool_choice='auto')
    return body


def decode(frames):
    buffer, reasoning = {}, []
    usage, finish, complete, has_text = None, None, False, False
    for _, raw in frames:
        if raw.strip() == '[DONE]':
            complete = True
            break
        chunk = object_json(raw)
        check_error(chunk)
        if chunk.get('usage') is not None:
            usage = _normalize_usage(chunk['usage'])
            yield {'type': 'usage', 'usage': usage}
        choices = chunk.get('choices', [])
        if not choices:
            continue
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProtocolError('模型 choices 格式无效')
        choice = choices[0]
        if choice.get('index', 0) != 0:
            raise ProtocolError('模型返回了未请求的候选回答')
        delta = choice.get('delta') or {}
        if not isinstance(delta, dict):
            raise ProtocolError('模型 delta 格式无效')
        if finish is not None and any(delta.get(key) for key in ('content', 'reasoning_content', 'tool_calls')):
            raise ProtocolError('模型在结束标记后继续返回内容')
        text, thought = delta.get('content'), delta.get('reasoning_content')
        for value in (text, thought):
            if value is not None and not isinstance(value, str):
                raise ProtocolError('模型文本片段格式无效')
        if text:
            has_text = True
            yield {'type': 'text', 'delta': text}
        if thought:
            reasoning.append(thought)
            yield progress()
        calls = delta.get('tool_calls') or []
        if not isinstance(calls, list):
            raise ProtocolError('模型工具调用格式无效')
        for part in calls:
            if not isinstance(part, dict):
                raise ProtocolError('模型工具片段格式无效')
            index = part.get('index')
            if type(index) is not int or not 0 <= index < MAX_CALLS:
                raise ProtocolError('模型工具索引无效')
            entry = buffer.setdefault(index, {'id': '', 'name': '', 'args': '', 'extra_content': {}})
            if part.get('type', 'function') != 'function':
                raise ProtocolError('不支持的模型工具类型')
            fn = part.get('function') or {}
            if not isinstance(fn, dict):
                raise ProtocolError('模型工具函数格式无效')
            for key, value in (('id', part.get('id')), ('name', fn.get('name'))):
                if value is not None:
                    if not isinstance(value, str) or (entry[key] and entry[key] != value):
                        raise ProtocolError('模型工具 ID 或名称发生冲突')
                    entry[key] = value
            args = fn.get('arguments', '')
            if not isinstance(args, str):
                raise ProtocolError('模型工具参数片段格式无效')
            entry['args'] += args
            if len(entry['args']) > MAX_ARGUMENTS:
                raise ProtocolError('模型工具参数超过限制')
            extra = part.get('extra_content')
            if extra is not None:
                if not isinstance(extra, dict):
                    raise ProtocolError('模型工具签名格式无效')
                # Gemini signatures are opaque; retain exactly for the next round.
                for key, value in extra.items():
                    if key in entry['extra_content'] and entry['extra_content'][key] != value:
                        raise ProtocolError('模型工具签名发生冲突')
                    entry['extra_content'][key] = deepcopy(value)
            yield progress()
        if choice.get('finish_reason') is not None:
            if finish is not None:
                raise ProtocolError('模型重复返回结束标记')
            finish = choice['finish_reason']
    if not complete or finish not in ('stop', 'tool_calls', 'length', 'content_filter'):
        raise ProtocolError('模型响应提前中断或缺少有效结束标记')
    if buffer and finish != 'tool_calls':
        raise ProtocolError('模型工具调用未正常完成，已阻止执行')
    if finish == 'tool_calls' and not buffer:
        raise ProtocolError('模型缺少工具调用内容')
    calls = unique_calls([tool_event(entry['id'], entry['name'], entry['args'],
                                    **({'extra_content': entry['extra_content']} if entry['extra_content'] else {}))
                          for _, entry in sorted(buffer.items())])
    if not has_text and not calls:
        raise ProtocolError('模型返回了空回答')
    yield from calls
    yield dict(type='done', reasoning_content=''.join(reasoning) or None, usage=usage, finish_reason=finish)
