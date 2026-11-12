"""Responses codec with explicit terminal status and stateless item replay."""
from copy import deepcopy

from .common import check_error, object_json, progress, tool_event, unique_calls
from .errors import _normalize_usage
from .transport import ProtocolError, ProviderError


def request_body(request):
    items = []
    for message in request.messages:
        role = message['role']
        state = message.get('provider_state') or {}
        if role == 'assistant' and state.get('protocol') == 'responses':
            items.extend(deepcopy(state['output']))
            continue
        if role == 'tool':
            items.append(dict(type='function_call_output', call_id=message['tool_call_id'],
                              output=message.get('content') or ''))
            continue
        content = message.get('content')
        if content:
            if isinstance(content, str):
                blocks = [dict(type='output_text' if role == 'assistant' else 'input_text', text=content)]
            else:
                blocks = []
                for part in content:
                    if part.get('type') == 'text':
                        blocks.append(dict(type='output_text' if role == 'assistant' else 'input_text', text=part['text']))
                    elif part.get('type') == 'image_url' and role != 'assistant':
                        blocks.append(dict(type='input_image', image_url=part['image_url']['url'],
                                           detail=part['image_url'].get('detail', 'auto')))
                    else:
                        raise ValueError('Responses 不支持该消息内容类型')
            items.append(dict(role=role, content=blocks))
        for call in message.get('tool_calls', []):
            items.append(dict(type='function_call', call_id=call['id'],
                              name=call['function']['name'], arguments=call['function']['arguments']))
    body = dict(model=request.model, input=items, stream=True, store=False,
                include=['reasoning.encrypted_content'], max_output_tokens=request.max_tokens)
    if not request.model.startswith(('o1', 'o3', 'o4', 'gpt-5')):
        body.update(temperature=request.temperature, top_p=request.top_p)
    if request.tools:
        body['tools'] = [dict(type='function', **tool['function']) for tool in request.tools]
    return body


def normalize_usage(usage):
    if usage is None:
        return None
    return _normalize_usage(dict(prompt_tokens=usage.get('input_tokens'),
                                 completion_tokens=usage.get('output_tokens'),
                                 total_tokens=usage.get('total_tokens'),
                                 prompt_tokens_details=usage.get('input_tokens_details')))


def decode(frames):
    terminal = None
    streamed = {}
    items, completed_items = {}, set()
    for event, raw in frames:
        chunk = object_json(raw)
        check_error(chunk)
        kind = chunk.get('type', event)
        if kind in ('response.completed', 'response.failed', 'response.incomplete'):
            response = chunk.get('response')
            if isinstance(response, dict) and response.get('usage') is not None:
                yield dict(type='usage', usage=normalize_usage(response['usage']))
        if kind == 'response.output_text.delta':
            delta = chunk.get('delta')
            if not isinstance(delta, str):
                raise ProtocolError('Responses 文本增量格式无效')
            index = (chunk.get('output_index', 0), chunk.get('content_index', 0))
            streamed[index] = streamed.get(index, '') + delta
            if delta:
                yield dict(type='text', delta=delta)
        elif kind == 'response.output_item.added':
            index, item = chunk.get('output_index'), chunk.get('item')
            if type(index) is not int or not 0 <= index < 128 or index in items or not isinstance(item, dict):
                raise ProtocolError('Responses 输出项索引无效')
            items[index] = item
            yield progress()
        elif kind == 'response.output_item.done':
            index, item = chunk.get('output_index'), chunk.get('item')
            if index not in items or index in completed_items or not isinstance(item, dict) or item.get('id') != items[index].get('id'):
                raise ProtocolError('Responses 输出项未正常完成')
            items[index] = item
            completed_items.add(index)
            yield progress()
        elif kind == 'response.completed':
            terminal = chunk.get('response')
            break
        elif kind in ('response.failed', 'response.incomplete'):
            response = chunk.get('response') or {}
            if response.get('error'):
                raise ProviderError(response)
            raise ProtocolError('Responses 响应未完成: ' + str(response.get('incomplete_details', {}).get('reason', kind)))
        elif kind.startswith(('response.function_call_arguments.', 'response.reasoning', 'response.refusal.')):
            yield progress()
        elif kind not in ('response.created', 'response.in_progress', 'response.queued',
                          'response.content_part.added', 'response.content_part.done', 'response.output_text.done'):
            raise ProtocolError('Responses 返回未知事件类型')
    if not isinstance(terminal, dict) or terminal.get('status') != 'completed':
        raise ProtocolError('Responses 缺少成功结束事件')
    output = terminal.get('output')
    if not isinstance(output, list):
        raise ProtocolError('Responses 缺少完整输出')
    if items and (set(items) != completed_items or len(items) != len(output) or any(items[i] != output[i] for i in items)):
        raise ProtocolError('Responses 完整输出与流式输出不一致')
    calls, full_text = [], {}
    for index, item in enumerate(output):
        kind = item.get('type')
        if kind == 'function_call':
            if item.get('status') != 'completed':
                raise ProtocolError('Responses 工具调用未完成')
            calls.append(tool_event(item.get('call_id'), item.get('name'), item.get('arguments')))
        elif kind == 'message':
            if item.get('status') != 'completed':
                raise ProtocolError('Responses 消息未完成')
            for part_index, part in enumerate(item.get('content', [])):
                if part.get('type') == 'output_text':
                    full_text[index, part_index] = part['text']
                elif part.get('type') == 'refusal':
                    raise ProtocolError('模型拒绝了此次请求: ' + part.get('refusal', ''))
                else:
                    raise ProtocolError('Responses 返回不支持的消息内容')
        elif kind != 'reasoning':
            raise ProtocolError('Responses 返回不支持的输出类型')
    calls = unique_calls(calls)
    if streamed and any(full_text.get(index) != value for index, value in streamed.items()):
        raise ProtocolError('Responses 文本流与最终输出不一致')
    for index, text in full_text.items():
        if index not in streamed and text:
            yield dict(type='text', delta=text)
    if not calls and not any(full_text.values()):
        raise ProtocolError('Responses 返回了空回答')
    yield from calls
    yield dict(type='done', usage=normalize_usage(terminal.get('usage')), reasoning_content=None, finish_reason='tool_calls' if calls else 'stop',
               provider_state=dict(protocol='responses', output=output))
