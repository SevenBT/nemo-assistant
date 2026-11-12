"""Offline wire contracts. Fixtures do not claim live provider certification."""
import copy
import json
from dataclasses import replace

import httpx
import pytest

from app.core.providers.adapter import HTTPProviderAdapter
from app.core.providers.contracts import LLMRequest
from app.core.providers.registry import endpoint, resolve_protocol
from app.core.providers import anthropic, chat, responses
from app.core.agent_hooks import _api_dicts_to_messages
from app.models.message import Message, ToolCall


def request(provider='openai', **kwargs):
    return replace(LLMRequest(trace_id='wire', attempt_id='wire', api_type='openai_chat',
                             model='test', provider=provider, api_key='dummy',
                             messages=[dict(role='user', content='hi')]), **kwargs)


def invoke(req, frames):
    seen = []
    def handle(wire):
        seen.append(wire)
        text = ''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames)
        return httpx.Response(200, text=text)
    adapter = HTTPProviderAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        events = [e for e in adapter.stream(req) if e['type'] != 'progress']
        return events, seen
    finally:
        adapter.close()


def claude_frames(blocks, finish='end_turn'):
    frames = [dict(type='message_start', message=dict(usage={'input_tokens': 8, 'output_tokens': 1,
                                                          'cache_read_input_tokens': 4}))]
    for index, block in enumerate(blocks):
        frames += [dict(type='content_block_start', index=index, content_block=block),
                   dict(type='content_block_stop', index=index)]
    return frames + [dict(type='message_delta', delta=dict(stop_reason=finish), usage={'output_tokens': 3}),
                     dict(type='message_stop')]


def test_claude_tools_images_usage_and_signed_blocks_roundtrip():
    blocks = [dict(type='thinking', thinking='private reasoning', signature='opaque-signature'),
              dict(type='tool_use', id='call_1', name='read_file', input={'path': 'a.txt'})]
    events, seen = invoke(request('anthropic'), claude_frames(blocks, 'tool_use'))
    assert events[0] == dict(type='tool_call', id='call_1', name='read_file', arguments={'path': 'a.txt'})
    done = events[-1]
    assert done['usage'] == dict(prompt_tokens=12, completion_tokens=3, total_tokens=15, cached_tokens=4)
    assistant = Message(role='assistant', provider_state=done['provider_state'],
                        reasoning_content=done['reasoning_content'],
                        tool_calls=[ToolCall(id='call_1', name='read_file', arguments={'path': 'a.txt'})])
    saved = Message.from_dict(json.loads(json.dumps(assistant.to_dict())))
    history = [dict(role='system', content='system'), dict(role='user', content=[
        dict(type='text', text='look'), dict(type='image_url', image_url={'url': 'data:image/png;base64,cGl4ZWxz'})]),
        saved.to_api_dict(), dict(role='tool', tool_call_id='call_1', content='result')]
    original = copy.deepcopy(history)
    body = anthropic.request_body(request('anthropic', messages=history))
    assert history == original
    assert body['messages'][0]['content'][1]['source'] == dict(type='base64', media_type='image/png', data='cGl4ZWxz')
    assert body['messages'][1]['content'] == blocks
    assert body['messages'][2]['content'][0]['tool_use_id'] == 'call_1'
    assert body['system'] == [dict(type='text', text='system')]
    assert seen[0].headers['x-api-key'] == 'dummy'
    assert 'authorization' not in seen[0].headers
    assert str(seen[0].url) == 'https://api.anthropic.com/v1/messages'
    assert _api_dicts_to_messages([saved.to_api_dict()])[0].provider_state == done['provider_state']


def test_claude_json_fragments_and_signature_fragments():
    frames = [dict(type='message_start', message={}),
              dict(type='content_block_start', index=0, content_block=dict(type='thinking', thinking='')),
              dict(type='content_block_delta', index=0, delta=dict(type='thinking_delta', thinking='think')),
              dict(type='content_block_delta', index=0, delta=dict(type='signature_delta', signature='sig')),
              dict(type='content_block_stop', index=0),
              dict(type='content_block_start', index=1, content_block=dict(type='tool_use', id='a', name='read_file', input={})),
              dict(type='content_block_delta', index=1, delta=dict(type='input_json_delta', partial_json='{"path":')),
              dict(type='content_block_delta', index=1, delta=dict(type='input_json_delta', partial_json='"a"}')),
              dict(type='content_block_stop', index=1),
              dict(type='message_delta', delta=dict(stop_reason='tool_use')), dict(type='message_stop')]
    events, _ = invoke(request('anthropic'), frames)
    assert events[0]['arguments'] == {'path': 'a'}
    assert events[-1]['provider_state']['content'][0]['signature'] == 'sig'


@pytest.mark.parametrize('change', ['eof', 'truncated', 'bad_json', 'bad_order'])
def test_claude_invalid_tools_never_execute(change):
    frames = claude_frames([dict(type='tool_use', id='a', name='exec', input={})], 'tool_use')
    if change == 'eof':
        frames.pop()
    elif change == 'truncated':
        frames[-2]['delta']['stop_reason'] = 'max_tokens'
    elif change == 'bad_json':
        frames.insert(2, dict(type='content_block_delta', index=0, delta=dict(type='input_json_delta', partial_json='{bad')))
    else:
        frames.insert(1, dict(type='content_block_delta', index=1, delta=dict(type='text_delta', text='x')))
    events, _ = invoke(request('anthropic'), frames)
    assert events[-1]['error_kind'] == 'protocol'
    assert not any(e['type'] in ('tool_call', 'done') for e in events)


def test_responses_replays_reasoning_and_tool_items_without_duplicate_text():
    output = [dict(type='reasoning', id='r1', summary=[], encrypted_content='opaque'),
              dict(type='function_call', id='fc1', call_id='call_1', name='read_file', arguments='{"path":"a"}', status='completed')]
    frames = [dict(type='response.created', response={'id': 'resp1'})]
    for i, item in enumerate(output):
        frames += [dict(type='response.output_item.added', output_index=i, item=item),
                   dict(type='response.output_item.done', output_index=i, item=item)]
    frames += [dict(type='response.completed', response=dict(status='completed', output=output,
                   usage=dict(input_tokens=10, output_tokens=4, total_tokens=14, input_tokens_details={'cached_tokens': 2})))]
    events, seen = invoke(request(api_protocol='responses'), frames)
    assert events[0]['id'] == 'call_1'
    assert events[-1]['usage']['cached_tokens'] == 2
    message = Message(role='assistant', provider_state=events[-1]['provider_state'])
    saved = Message.from_dict(message.to_dict())
    body = responses.request_body(request(api_protocol='responses', messages=[
        saved.to_api_dict(), dict(role='tool', tool_call_id='call_1', content='result')]))
    assert body['input'][:2] == output
    assert body['input'][-1] == dict(type='function_call_output', call_id='call_1', output='result')
    assert body['store'] is False
    assert str(seen[0].url) == 'https://api.openai.com/v1/responses'


def test_responses_text_and_image_translation():
    item = dict(type='message', id='m1', role='assistant', status='completed', content=[dict(type='output_text', text='ok', annotations=[])])
    frames = [dict(type='response.output_item.added', output_index=0, item=dict(item, status='in_progress')),
              dict(type='response.output_text.delta', output_index=0, content_index=0, delta='ok'),
              dict(type='response.output_item.done', output_index=0, item=item),
              dict(type='response.completed', response=dict(status='completed', output=[item]))]
    events, seen = invoke(request(api_protocol='responses', messages=[dict(role='user', content=[
        dict(type='image_url', image_url={'url': 'data:image/png;base64,AA=='})])]), frames)
    assert [e['delta'] for e in events if e['type'] == 'text'] == ['ok']
    assert events[-1]['usage'] is None
    assert json.loads(seen[0].content)['input'][0]['content'][0]['type'] == 'input_image'


@pytest.mark.parametrize('terminal', ['response.incomplete', 'response.failed', 'missing', 'bad_arguments'])
def test_responses_incomplete_or_invalid_tools_never_execute(terminal):
    output = [dict(type='function_call', id='fc', call_id='a', name='exec', arguments='{bad' if terminal == 'bad_arguments' else '{}', status='completed')]
    frames = [dict(type='response.output_item.added', output_index=0, item=output[0])]
    if terminal == 'bad_arguments':
        frames.append(dict(type='response.output_item.done', output_index=0, item=output[0]))
    if terminal != 'missing':
        frames += [dict(type=terminal if terminal != 'bad_arguments' else 'response.completed',
                        response=dict(status='completed', output=output))]
    events, _ = invoke(request(api_protocol='responses'), frames)
    assert events[-1]['type'] == 'error'
    assert not any(e['type'] in ('tool_call', 'done') for e in events)


@pytest.mark.parametrize('stage', ['start', 'delta'])
def test_claude_failed_stream_retains_latest_reported_usage(stage):
    frames = [dict(type='message_start', message=dict(usage={'input_tokens': 8, 'cache_read_input_tokens': 4}))]
    if stage == 'delta':
        frames.append(dict(type='message_delta', delta=dict(stop_reason='end_turn'), usage={'output_tokens': 3}))
    events, _ = invoke(request('anthropic'), frames)
    error = events[-1]
    assert error['error_kind'] == 'protocol'
    assert error['usage']['prompt_tokens'] == 12
    assert error['usage']['completion_tokens'] == (3 if stage == 'delta' else None)
    assert error['usage']['total_tokens'] == (15 if stage == 'delta' else None)
    assert not any(e['type'] in ('usage', 'tool_call', 'done') for e in events)


@pytest.mark.parametrize('status', ['failed', 'incomplete', 'completed'])
def test_responses_failed_or_invalid_output_retains_reported_usage(status):
    response = dict(status=status, output=[dict(type='function_call', id='fc', call_id='a',
                    name='exec', arguments='{bad', status='completed')],
                    usage=dict(input_tokens=8, output_tokens=3))
    if status == 'failed':
        response['error'] = dict(code='server_error', message='failed')
    events, _ = invoke(request(api_protocol='responses'), [dict(type='response.' + status, response=response)])
    assert events[-1]['type'] == 'error'
    assert events[-1]['usage']['total_tokens'] == 11
    assert not any(e['type'] in ('usage', 'tool_call', 'done') for e in events)


def test_cohere_invalid_tool_retains_reported_usage():
    frames = [dict(type='message-start'),
              dict(type='message-end', delta=dict(finish_reason='TOOL_CALL',
                   usage=dict(tokens=dict(input_tokens=8, output_tokens=3))))]
    events, _ = invoke(request('cohere'), frames)
    assert events[-1]['error_kind'] == 'protocol'
    assert events[-1]['usage']['total_tokens'] == 11
    assert not any(e['type'] in ('usage', 'tool_call', 'done') for e in events)


def test_gemini_signature_survives_storage_and_next_request():
    signature = {'google': {'thought_signature': 'opaque-google-signature'}}
    frames = [dict(choices=[dict(index=0, delta=dict(tool_calls=[dict(index=0, id='a', type='function',
                  function={'name': 'read_file', 'arguments': '{}'}, extra_content=signature)]), finish_reason='tool_calls')])]
    # The common chat decoder requires the Chat Completions terminal sentinel.
    events = list(chat.decode(iter([('', json.dumps(frames[0])), ('', '[DONE]')])))
    call = next(e for e in events if e['type'] == 'tool_call')
    msg = Message(role='assistant', tool_calls=[ToolCall(id='a', name='read_file', arguments={}, extra_content=call['extra_content'])])
    saved = Message.from_dict(json.loads(json.dumps(msg.to_dict())))
    body = chat.request_body(request('gemini', messages=[saved.to_api_dict()]))
    assert body['messages'][0]['tool_calls'][0]['extra_content'] == signature
    assert _api_dicts_to_messages([saved.to_api_dict()])[0].tool_calls[0].extra_content == signature


def test_cohere_native_stream_and_tool_request():
    frames = [dict(type='message-start'),
              dict(type='tool-call-start', index=0, delta={'message': {'tool_calls': {'id': 'a', 'type': 'function', 'function': {'name': 'read_file', 'arguments': ''}}}}),
              dict(type='tool-call-delta', index=0, delta={'message': {'tool_calls': {'function': {'arguments': '{}'}}}}),
              dict(type='tool-call-end', index=0),
              dict(type='message-end', delta={'finish_reason': 'TOOL_CALL', 'usage': {'tokens': {'input_tokens': 3, 'output_tokens': 2}}})]
    events, seen = invoke(request('cohere'), frames)
    assert events[0]['arguments'] == {}
    assert events[-1]['usage']['total_tokens'] == 5
    assert str(seen[0].url) == 'https://api.cohere.com/v2/chat'
    assert 'stream_options' not in json.loads(seen[0].content)


@pytest.mark.parametrize('provider,suffix', [('openai', '/v1/chat/completions'), ('deepseek', '/chat/completions'),
    ('gemini', '/v1beta/openai/chat/completions'), ('dashscope', '/compatible-mode/v1/chat/completions'),
    ('zai', '/api/paas/v4/chat/completions'), ('meta_llama', '/compat/v1/chat/completions'),
    ('anthropic', '/v1/messages'), ('cohere', '/v2/chat')])
def test_default_profile_endpoints(provider, suffix):
    assert endpoint(provider, '', resolve_protocol(provider)).endswith(suffix)


def test_unknown_provider_requires_explicit_endpoint_and_azure_keeps_resource_host():
    with pytest.raises(ValueError):
        endpoint('unknown', '', 'openai_chat')
    assert endpoint('azure', 'https://resource.openai.azure.com', 'openai_chat') == 'https://resource.openai.azure.com/openai/v1/chat/completions'
    assert endpoint('custom', 'http://localhost:9000/v1', 'responses') == 'http://localhost:9000/v1/responses'


def test_reasoning_model_does_not_receive_unsupported_sampling_controls():
    body = chat.request_body(request(model='gpt-5-test'))
    assert 'temperature' not in body and 'top_p' not in body and 'max_tokens' not in body
    assert body['max_completion_tokens'] == 4096


@pytest.mark.parametrize('protocol', ['openai_chat', 'anthropic_messages', 'responses'])
def test_agent_next_iteration_retains_provider_history(protocol):
    from app.core.agent import Agent
    from app.core.agent_context import AgentContext
    from app.core.agent_interface import AgentCallbacks
    from app.core.providers.common import tool_event
    signature = {'google': {'thought_signature': 'signed'}}
    state = {'protocol': protocol, 'output': [{'type': 'reasoning', 'encrypted_content': 'opaque'}]}
    records, completed = [], []
    class Gateway:
        def chat_stream(self, messages, tools, **kwargs):
            records.append(copy.deepcopy(messages))
            if len(records) == 1:
                yield tool_event('a', 'read_file', {'path': 'a'}, extra_content=signature)
                yield dict(type='done', provider_state=state, reasoning_content='thought')
            else:
                yield dict(type='text', delta='answer')
                yield dict(type='done')
    class Registry:
        def get_openai_functions(self):
            return []
        def get(self, name):
            return type('Tool', (), {'read_only': False})()
        def execute(self, name, params):
            return {'status': 'success', 'data': 'result'}
    agent = Agent(AgentContext(llm_gateway=Gateway(), registry=Registry(),
                  callbacks=AgentCallbacks(on_message_complete=completed.append)),
                  [dict(role='user', content='read')], session_id='')
    result = agent.run_sync()
    assert result['ok']
    assistant = records[1][-2]
    assert assistant['provider_state'] == state
    assert assistant['reasoning_content'] == 'thought'
    assert assistant['tool_calls'][0]['extra_content'] == signature
    assert records[1][-1]['tool_call_id'] == 'a'
    assert completed[0]['provider_state'] == state
    assert completed[1]['provider_state'] == {}


def test_sdk_dependencies_are_absent_from_runtime_manifests_and_install():
    import importlib.util
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    forbidden = {'litellm', 'openai', 'anthropic'}
    for name in forbidden:
        assert importlib.util.find_spec(name) is None
    for lock in (root / 'uv.lock', root / 'evals/uv.lock'):
        packages = tomllib.loads(lock.read_text(encoding='utf-8'))['package']
        assert not forbidden.intersection(package['name'] for package in packages)
