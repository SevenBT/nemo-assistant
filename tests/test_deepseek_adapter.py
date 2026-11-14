"""Offline protocol contracts for the SDK-free route. No desktop hooks or APIs."""
import asyncio
import copy
import json
import subprocess
import sys
import textwrap
import time
from dataclasses import replace

import httpx
import pytest

from app.llm.cancellation import CancellationToken
from app.llm.providers.adapter import HTTPProviderAdapter
from app.llm.llm_gateway import GatewayLogger, LLMGateway, LLMRequest, RetryPolicy
from app.llm.runtime_config import GatewayConfig


class WireStream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            if isinstance(part, Exception):
                raise part
            yield part

    async def aclose(self):
        self.closed = True


def frame(delta=None, finish=None, usage=None):
    result = {'choices': [] if delta is None else [
        {'index': 0, 'delta': delta, 'finish_reason': finish}
    ]}
    if usage is not None:
        result['usage'] = usage
    return result


def wire(*frames, done=True):
    data = b''.join(('data: ' + json.dumps(f, ensure_ascii=False) + '\r\n\r\n').encode()
                    for f in frames)
    if done:
        data += b'data: [DONE]\r\n\r\n'
    # Split UTF-8 and SSE delimiters across arbitrary network boundaries.
    return WireStream([data[i:i + 7] for i in range(0, len(data), 7)])


def request(**kwargs):
    return replace(LLMRequest(
        trace_id='test', attempt_id='attempt', api_type='openai_chat',
        model='deepseek-test', provider='deepseek', api_key='test-secret-key',
        messages=[{'role': 'user', 'content': 'hi'}],
    ), **kwargs)


@pytest.fixture
def transport():
    owned = []

    def create(stream, *, status=200, headers=None):
        seen = []

        def handle(req):
            seen.append(req)
            return httpx.Response(status, stream=stream, headers=headers)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = HTTPProviderAdapter(client)
        owned.append(adapter)
        return adapter, seen, client

    yield create
    for adapter in owned:
        adapter.close()


def test_streaming_text_reasoning_usage_and_request_contract(transport):
    stream = wire(
        frame({'role': 'assistant', 'reasoning_content': '思考'}),
        frame({'content': '你好'}), frame({'content': '世界'}, 'stop'),
        frame(usage={'prompt_tokens': 9, 'completion_tokens': 2, 'total_tokens': 11,
                     'prompt_cache_hit_tokens': 4}),
    )
    adapter, seen, client = transport(stream)
    events = [e for e in adapter.stream(request(max_tokens=100, temperature=0.3, top_p=0.9)) if e['type'] != 'progress']
    assert events[:2] == [{'type': 'text', 'delta': '你好'}, {'type': 'text', 'delta': '世界'}]
    assert events[-1] == {'type': 'done', 'reasoning_content': '思考', 'finish_reason': 'stop',
                          'usage': {'prompt_tokens': 9, 'completion_tokens': 2,
                                    'total_tokens': 11, 'cached_tokens': 4}}
    body = json.loads(seen[0].content)
    assert body == {
        'model': 'deepseek-test', 'messages': [{'role': 'user', 'content': 'hi'}],
        'max_tokens': 100, 'temperature': 0.3, 'top_p': 0.9, 'stream': True,
        'stream_options': {'include_usage': True}, 'thinking': {'type': 'disabled'},
    }
    assert str(seen[0].url) == 'https://api.deepseek.com/chat/completions'
    assert seen[0].headers['authorization'] == 'Bearer test-secret-key'
    assert stream.closed
    assert not client.is_closed  # Return the connection to a persistent client.
    adapter.close()
    assert client.is_closed


@pytest.mark.parametrize('base,expected', [
    ('', 'https://api.deepseek.com/beta/chat/completions'),
    ('https://proxy.test/v1/', 'https://proxy.test/v1/chat/completions'),
    ('https://proxy.test/beta/chat/completions', 'https://proxy.test/beta/chat/completions'),
])
def test_multiround_images_and_tool_schema_reach_configured_endpoint(transport, base, expected):
    adapter, seen, _ = transport(wire(frame({'content': 'ok'}, 'stop')))
    messages = [
        {'role': 'user', 'content': [
            {'type': 'text', 'text': 'describe'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,pixels'}},
        ]},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'a', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'a', 'content': 'file contents'},
        {'role': 'user', 'content': 'continue'},
    ]
    tools = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}]
    original = copy.deepcopy(messages)
    list(adapter.stream(request(base_url=base, messages=messages, tools=tools)))
    body = json.loads(seen[0].content)
    assert body['messages'] == original == messages
    assert body['tools'] == tools
    assert body['tool_choice'] == 'auto'
    assert str(seen[0].url) == expected


def test_parallel_tool_fragments_are_assembled_before_execution(transport):
    stream = wire(
        frame({'tool_calls': [
            {'index': 1, 'id': 'b', 'function': {'name': 'save_file', 'arguments': '{"path":'}},
            {'index': 0, 'id': 'a', 'function': {'name': 'read_file', 'arguments': '{"path":"'}}]}),
        frame({'tool_calls': [
            {'index': 0, 'function': {'arguments': '你好.txt"}'}},
            {'index': 1, 'function': {'arguments': '"b.txt"}'}}]}, 'tool_calls'),
        frame(usage={'prompt_tokens': 3, 'completion_tokens': 5}),
    )
    adapter, _, _ = transport(stream)
    events = [e for e in adapter.stream(request()) if e['type'] != 'progress']
    assert events[:2] == [
        {'type': 'tool_call', 'id': 'a', 'name': 'read_file', 'arguments': {'path': '你好.txt'}},
        {'type': 'tool_call', 'id': 'b', 'name': 'save_file', 'arguments': {'path': 'b.txt'}},
    ]
    assert events[-1]['usage']['total_tokens'] == 8


@pytest.mark.parametrize('payload', [
    wire(frame({'content': 'partial'}, 'stop'), done=False),
    wire(frame({'content': 'partial'})),  # DONE without a finish reason.
    wire(frame({}, 'stop')),  # A terminal but empty answer.
    wire(frame({'tool_calls': [{'id': 'a', 'index': 0,
                              'function': {'name': 'exec', 'arguments': '{broken'}}]}, 'tool_calls')),
    wire(frame({'tool_calls': [{'id': 'a', 'index': 0,
                              'function': {'name': 'exec', 'arguments': '[]'}}]}, 'tool_calls')),
    wire(frame({'tool_calls': [{'id': 'a', 'index': 0,
                              'function': {'name': 'exec', 'arguments': '{}'}}]}, 'length')),
    wire(frame({'tool_calls': [{'id': 'a', 'index': 0,
                              'function': {'name': 'exec'}}]}, 'tool_calls')),
    WireStream([b'data: invalid-json\n\n']),
])
def test_invalid_streams_cannot_complete_or_execute_partial_tools(transport, payload):
    adapter, _, _ = transport(payload)
    events = list(adapter.stream(request()))
    assert events[-1]['type'] == 'error'
    assert events[-1]['error_kind'] == 'protocol'
    assert not any(e['type'] in ('tool_call', 'done') for e in events)
    assert payload.closed


def test_sse_comments_and_multiline_fields(transport):
    stream = WireStream([b': keep-alive\n\nevent: message\nid: 1\ndata: {"choices":\n',
                         b'data: [{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n',
                         b'data: [DONE]\n\n'])
    adapter, _, _ = transport(stream)
    assert list(adapter.stream(request()))[-1]['type'] == 'done'


def test_cancel_and_early_consumer_close_release_response(transport):
    for cancel in (True, False):
        stream = wire(frame({'content': 'partial'}), frame({}, 'stop'))
        adapter, _, _ = transport(stream)
        token = CancellationToken()
        events = adapter.stream(request(), token)
        assert next(events)['type'] == 'text'
        if cancel:
            token.cancel()
            assert list(events) == []
        else:
            events.close()
        assert stream.closed
        assert token._resources == []


@pytest.mark.parametrize('base', ['https://user:secret@proxy.test/v1', 'https://proxy.test/v1?key=secret'])
def test_invalid_endpoint_is_rejected_without_a_request(transport, base):
    adapter, seen, _ = transport(wire())
    assert list(adapter.stream(request(base_url=base)))[-1]['type'] == 'error'
    assert seen == []


def test_http_error_keeps_status_retry_after_and_redacts_key(transport):
    stream = WireStream([json.dumps({'error': {'message': 'test-secret-key invalid',
                                            'code': 'insufficient_quota'}}).encode()])
    adapter, _, _ = transport(stream, status=429, headers={'Retry-After': '2'})
    event = list(adapter.stream(request()))[-1]
    assert event['status_code'] == 429
    assert event['retry_after'] == 2
    assert event['error_code'] == 'insufficient_quota'
    assert 'test-secret-key' not in event['message']
    assert not RetryPolicy().is_retryable(event)


def test_gateway_retries_before_output_but_never_after_partial_text_or_falls_back(tmp_path):
    for partial in (False, True):
        calls = []

        def handle(req):
            calls.append(req)
            if len(calls) == 1:
                if partial:
                    stream = wire(frame({'content': 'partial'}), done=False)
                    stream.parts.append(httpx.ReadError('disconnected'))
                    return httpx.Response(200, stream=stream)
                return httpx.Response(503, json={'error': {'message': 'busy'}})
            return httpx.Response(200, stream=wire(frame({'content': 'ok'}, 'stop')))

        adapter = HTTPProviderAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        with LLMGateway(
            config=GatewayConfig(provider='deepseek', model='test', api_key='dummy'),
            adapters={'openai_chat': adapter},
            retry_policy=RetryPolicy(max_attempts=2, sleep=lambda _: None),
            logger=GatewayLogger(tmp_path / f'{partial}.jsonl'),
        ) as gateway:
            events = list(gateway.chat_stream([{'role': 'user', 'content': 'hi'}]))
        assert len(calls) == (1 if partial else 2)
        assert events[-1]['type'] == ('error' if partial else 'done')
        records = [json.loads(line) for line in (tmp_path / f'{partial}.jsonl').read_text().splitlines()]
        assert len(records) == len(calls)
        assert all(r['api_type'] == 'openai_chat' for r in records)


def test_provider_sse_errors_preserve_usage_without_inventing_charges(transport):
    adapter, _, _ = transport(wire(
        frame(usage={'prompt_tokens': 5}),
        {'error': {'message': 'invalid request', 'type': 'invalid_request_error'}},
    ))
    event = list(adapter.stream(request()))[-1]
    assert event['type'] == 'error'
    assert event['usage']['prompt_tokens'] == 5
    assert 'provider_cost' not in event


def test_routes_resolve_to_explicit_wire_protocols():
    from app.llm.runtime_config import provider_api_type
    assert provider_api_type('anthropic') == 'anthropic_messages'
    assert provider_api_type('openai', 'responses') == 'responses'
    for provider in ('deepseek', 'openai', 'gemini', '', 'custom'):
        assert provider_api_type(provider) == 'openai_chat'


def test_deadline_closes_response_even_when_server_only_sends_keepalives(transport):
    class KeepaliveStream(WireStream):
        async def __aiter__(self):
            deadline = time.monotonic() + 2
            while not self.closed and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
                yield b': keepalive\n\n'

    stream = KeepaliveStream([])
    adapter, _, _ = transport(stream)
    events = list(adapter.stream(request(stream_timeout=0.04)))
    assert stream.closed
    assert events[-1]['type'] == 'error'
    assert events[-1]['error_kind'] == 'timeout'


def test_clean_process_chat_and_consult_work_when_sdk_imports_are_forbidden():
    # Fresh interpreter proves this is not merely reuse of a previously loaded SDK.
    script = textwrap.dedent('''
        import builtins, json, sys
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in ('litellm', 'openai', 'anthropic', 'PyQt6', 'qfluentwidgets', 'uiautomation', 'keyring') or name == 'app.config.config':
                raise AssertionError('Forbidden dependency: ' + name)
            return original_import(name, *args, **kwargs)
        builtins.__import__ = guarded_import
        import httpx
        from app.agent.agent import Agent
        from app.agent.agent_context import AgentContext
        from app.agent.agent_interface import AgentCallbacks
        from app.conversation.conversation_prompt_builder import ConversationPromptBuilder
        from app.conversation.consolidator import Consolidator
        from app.conversation.dream import Dream
        from app.observability.trace_store import TraceStore
        from app.observability.diagnostics import build_diagnostic
        from app.llm.providers.adapter import HTTPProviderAdapter
        from app.llm.providers import adapter as adapter_module
        from app.llm import llm_gateway
        from app.llm.runtime_config import GatewayConfig
        from app.tools.multi_model_consult import MultiModelConsultTool
        def handle(request):
            payload = {'choices': [{'delta': {'content': 'ok'}, 'finish_reason': 'stop'}]}
            return httpx.Response(200, text='data: ' + json.dumps(payload) + '\\n\\ndata: [DONE]\\n\\n')
        real_gateway = llm_gateway.LLMGateway
        adapter_module.HTTPProviderAdapter = lambda: HTTPProviderAdapter(
            httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        def create(**kwargs):
            return real_gateway(**kwargs, logger=llm_gateway.GatewayLogger.disabled())
        with create(config=GatewayConfig(model='test', provider='deepseek', api_key='dummy')) as gateway:
            assert list(gateway.chat_stream([{'role': 'user', 'content': 'hi'}]))[-1]['type'] == 'done'
        llm_gateway.LLMGateway = create
        result = MultiModelConsultTool(model='test', provider='deepseek', api_key='dummy').execute(
            {'query': 'design', 'perspectives': ['architect']})
        assert result['status'] == 'success' and 'ok' in result['data']['result']
        assert not any(n.split('.')[0] in ('litellm', 'openai', 'anthropic', 'PyQt6', 'qfluentwidgets', 'uiautomation', 'keyring') for n in sys.modules)
        assert 'app.config.config' not in sys.modules
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
