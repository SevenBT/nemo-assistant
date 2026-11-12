"""Consultation must share gateway semantics, without untracked SDK calls."""
import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from app.llm.providers.adapter import HTTPProviderAdapter
from app.llm.llm_gateway import GatewayLogger
from app.tools.multi_model_consult import MultiModelConsultTool


def test_deepseek_consult_uses_lightweight_gateway_and_records_tokens(monkeypatch, tmp_path):
    import app.llm.llm_gateway as module
    calls = []
    barrier = threading.Barrier(2)

    async def handle(request):
        calls.append(json.loads(request.content))
        await asyncio.to_thread(barrier.wait, timeout=3)
        data = {'choices': [{'delta': {'content': 'analysis'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 7, 'completion_tokens': 2, 'total_tokens': 9}}
        return httpx.Response(200, text='data: ' + json.dumps(data) + '\n\ndata: [DONE]\n\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    real_gateway = module.LLMGateway
    log = tmp_path / 'consult.jsonl'
    monkeypatch.setattr(module, 'LLMGateway', lambda **kwargs: real_gateway(
        **kwargs, adapters={'openai_chat': HTTPProviderAdapter(client)}, logger=GatewayLogger(log)))
    tool = MultiModelConsultTool(model='test', provider='deepseek', api_key='dummy')
    result = tool.execute({'query': 'design', 'perspectives': ['architect', 'security'], 'timeout': 3})
    assert result['status'] == 'success'
    assert result['data']['result'].count('analysis') == 2
    assert len(calls) == 2
    assert len({c['messages'][0]['content'] for c in calls}) == 2
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 2
    assert all(row['total_tokens'] == 9 and row['api_type'] == 'openai_chat' for row in rows)
    assert client.is_closed


def test_consult_timeout_cancels_worker_before_closing_shared_gateway(monkeypatch):
    state = SimpleNamespace(tokens=[], stopped=threading.Event(), closed=False)

    class Gateway:
        def __init__(self, **kwargs):
            pass

        def chat_stream(self, messages, cancel_token, stream_timeout):
            state.tokens.append(cancel_token)
            assert cancel_token.wait(2), 'Timed-out consultation must cancel the underlying call'
            state.stopped.set()
            if False:
                yield

        def close(self):
            state.closed = True

    monkeypatch.setattr('app.llm.llm_gateway.LLMGateway', Gateway)
    tool = MultiModelConsultTool(model='test', provider='deepseek', api_key='dummy')
    result = tool.execute({'query': 'design', 'perspectives': ['architect'], 'timeout': 0.05})
    assert '超时' in result['data']['result']
    assert state.tokens and state.tokens[0].is_cancelled()
    assert state.stopped.is_set() and state.closed


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), 'invalid'])
def test_invalid_consult_timeout_is_rejected(timeout):
    tool = MultiModelConsultTool()
    assert tool.execute({'query': 'design', 'timeout': timeout})['status'] == 'error'
