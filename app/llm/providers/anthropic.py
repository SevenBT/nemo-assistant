"""Native Claude Messages codec with lossless assistant block replay."""
from copy import deepcopy

from .common import MAX_ARGUMENTS, MAX_CALLS, check_error, object_json, progress, tool_event, unique_calls
from .errors import _normalize_usage
from .transport import ProtocolError


def content_blocks(content):
    if content is None:
        return []
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}] if content else []
    if not isinstance(content, list):
        raise ValueError('Claude 消息内容格式无效')
    result = []
    for part in content:
        if part.get('type') == 'text':
            result.append(deepcopy(part))
        elif part.get('type') == 'image_url':
            url = part['image_url']['url']
            if url.startswith('data:'):
                header, data = url.split(',', 1)
                if not header.endswith(';base64'):
                    raise ValueError('Claude 图片需要 base64 编码')
                source = dict(type='base64', media_type=header[5:-7], data=data)
            else:
                source = dict(type='url', url=url)
            result.append(dict(type='image', source=source))
        else:
            raise ValueError('Claude 不支持该消息内容类型')
    return result


def request_body(request):
    messages, system = [], []
    for message in request.messages:
        role = message['role']
        if role in ('system', 'developer'):
            system.extend(content_blocks(message.get('content')))
            continue
        state = message.get('provider_state') or {}
        if role == 'assistant' and state.get('protocol') == 'anthropic_messages':
            blocks = deepcopy(state['content'])
        elif role == 'tool':
            blocks = [dict(type='tool_result', tool_use_id=message['tool_call_id'],
                           content=message.get('content') or '')]
        else:
            blocks = content_blocks(message.get('content'))
            for call in message.get('tool_calls', []):
                fn = call['function']
                blocks.append(dict(type='tool_use', id=call['id'], name=fn['name'],
                                   input=object_json(fn['arguments'])))
        wire_role = 'assistant' if role == 'assistant' else 'user'
        if blocks:
            if messages and messages[-1]['role'] == wire_role:
                messages[-1]['content'].extend(blocks)
            else:
                messages.append(dict(role=wire_role, content=blocks))
    body = dict(model=request.model, messages=messages, max_tokens=request.max_tokens,
                temperature=request.temperature, stream=True)
    if system:
        body['system'] = system
    if request.tools:
        body['tools'] = [dict(name=t['function']['name'],
                              description=t['function'].get('description', ''),
                              input_schema=t['function'].get('parameters', {'type': 'object'}))
                         for t in request.tools]
    return body


def normalize_usage(usage):
    prompt = usage.get('input_tokens')
    if prompt is not None:
        prompt += usage.get('cache_creation_input_tokens', 0) + usage.get('cache_read_input_tokens', 0)
    return _normalize_usage(dict(prompt_tokens=prompt, completion_tokens=usage.get('output_tokens'),
                                 cached_tokens=usage.get('cache_read_input_tokens')))


def decode(frames):
    blocks, active, arguments = {}, set(), {}
    started = ended = False
    finish, usage = None, {}
    for event, raw in frames:
        chunk = object_json(raw)
        check_error(chunk)
        kind = chunk.get('type', event)
        if kind == 'ping':
            continue
        if kind == 'message_start':
            if started:
                raise ProtocolError('Claude 重复开始消息')
            started = True
            usage.update(chunk.get('message', {}).get('usage') or {})
            yield dict(type='usage', usage=normalize_usage(usage))
        elif kind == 'content_block_start':
            index = chunk.get('index')
            if not started or type(index) is not int or not 0 <= index < MAX_CALLS or index in blocks:
                raise ProtocolError('Claude 内容块索引无效')
            block = deepcopy(chunk.get('content_block'))
            if not isinstance(block, dict) or block.get('type') not in ('text', 'tool_use', 'thinking', 'redacted_thinking'):
                raise ProtocolError('Claude 返回不支持的内容块')
            blocks[index], arguments[index] = block, ''
            active.add(index)
            if block['type'] == 'text' and block.get('text'):
                yield dict(type='text', delta=block['text'])
            yield progress()
        elif kind == 'content_block_delta':
            index, delta = chunk.get('index'), chunk.get('delta', {})
            if index not in active:
                raise ProtocolError('Claude 内容块尚未开始或已经结束')
            block, delta_type = blocks[index], delta.get('type')
            fields = {'text_delta': ('text', 'text'), 'thinking_delta': ('thinking', 'thinking'),
                      'signature_delta': ('thinking', 'signature')}
            if delta_type == 'input_json_delta' and block['type'] == 'tool_use':
                arguments[index] += delta['partial_json']
                if len(arguments[index]) > MAX_ARGUMENTS:
                    raise ProtocolError('Claude 工具参数超过限制')
            elif delta_type in fields and block['type'] == fields[delta_type][0]:
                field = fields[delta_type][1]
                value = delta.get(field)
                if not isinstance(value, str):
                    raise ProtocolError('Claude 文本增量格式无效')
                block[field] = block.get(field, '') + value
                if delta_type == 'text_delta' and value:
                    yield dict(type='text', delta=value)
            else:
                raise ProtocolError('Claude 返回不支持的内容增量')
            yield progress()
        elif kind == 'content_block_stop':
            index = chunk.get('index')
            if index not in active:
                raise ProtocolError('Claude 内容块重复结束')
            active.remove(index)
            if blocks[index]['type'] == 'tool_use' and arguments[index]:
                blocks[index]['input'] = object_json(arguments[index])
        elif kind == 'message_delta':
            finish = chunk.get('delta', {}).get('stop_reason') or finish
            usage.update(chunk.get('usage') or {})
            yield dict(type='usage', usage=normalize_usage(usage))
        elif kind == 'message_stop':
            ended = True
            break
        else:
            raise ProtocolError('Claude 返回未知事件类型')
    if not started or not ended or active or finish not in ('end_turn', 'tool_use', 'max_tokens', 'stop_sequence', 'refusal', 'pause_turn'):
        raise ProtocolError('Claude 响应未完整结束')
    content = [block for _, block in sorted(blocks.items())]
    calls = unique_calls([tool_event(b.get('id'), b.get('name'), b.get('input')) for b in content if b['type'] == 'tool_use'])
    if (calls and finish != 'tool_use') or (finish == 'tool_use' and not calls):
        raise ProtocolError('Claude 工具调用未正常完成，已阻止执行')
    if not calls and not any(b['type'] == 'text' and b.get('text') for b in content):
        raise ProtocolError('Claude 返回了空回答')
    yield from calls
    yield dict(type='done', finish_reason=finish, usage=normalize_usage(usage),
               reasoning_content=''.join(b.get('thinking', '') for b in content) or None,
               provider_state=dict(protocol='anthropic_messages', content=content))
