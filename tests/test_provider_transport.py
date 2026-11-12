"""Real loopback sockets exercise waiting for headers, keepalives and pooling."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.llm.cancellation import CancellationToken
from app.llm.providers.adapter import HTTPProviderAdapter
from app.llm.providers.contracts import LLMRequest
from app.llm.providers.transport import HttpTransport, MAX_EVENT


@pytest.fixture
def server():
    entered = threading.Event()
    release = threading.Event()
    disconnected = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            try:
                if self.path.startswith('/headers/'):
                    entered.set()
                    release.wait(3)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                if self.path.startswith('/keepalive/'):
                    entered.set()
                    for _ in range(200):
                        self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                        if release.wait(.01):
                            break
                else:
                    frame = {'choices': [{'delta': {'content': 'ok'}, 'finish_reason': 'stop'}]}
                    self.wfile.write(('data: ' + json.dumps(frame) + '\n\ndata: [DONE]\n\n').encode())
                    self.wfile.flush()
            except (ConnectionError, OSError):
                disconnected.set()
            finally:
                self.close_connection = True
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}', entered, release, disconnected
    release.set()
    httpd.shutdown()
    httpd.server_close()
    thread.join(2)


def req(base, path='', timeout=None):
    return LLMRequest(trace_id='socket', attempt_id='socket', api_type='openai_chat',
                      provider='custom', base_url=base + path, api_key='dummy', model='test',
                      messages=[dict(role='user', content='hi')], stream_timeout=timeout)


def adapter():
    return HTTPProviderAdapter(httpx.AsyncClient(trust_env=False))


def test_cancel_during_header_wait_releases_call_and_does_not_close_pool(server):
    base, entered, release, _ = server
    token = CancellationToken()
    client = adapter()
    try:
        with ThreadPoolExecutor() as pool:
            call = pool.submit(lambda: list(client.stream(req(base, '/headers'), token)))
            assert entered.wait(2)
            start = time.monotonic()
            token.cancel()
            assert call.result(1) == []
            assert time.monotonic() - start < 1
            assert token._resources == []
            assert not client.transport._calls
            # Another request on the same connection pool remains usable.
            assert list(client.stream(req(base)))[-1]['type'] == 'done'
        assert not client.transport._client.is_closed
    finally:
        release.set()
        client.close()
    assert client.transport._client.is_closed
    assert not client.transport._thread.is_alive()
    assert client.transport._loop.is_closed()


def test_total_deadline_applies_during_keepalive_only_stream(server):
    base, _, _, disconnected = server
    client = adapter()
    try:
        start = time.monotonic()
        events = list(client.stream(req(base, '/keepalive', .15)))
        assert time.monotonic() - start < 1.5
        assert events[-1]['error_kind'] == 'timeout'
        assert disconnected.wait(1)
        assert not client.transport._calls
    finally:
        client.close()


def test_cancelling_one_concurrent_call_preserves_other_call(server):
    base, entered, release, _ = server
    client = adapter()
    token = CancellationToken()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocked = pool.submit(lambda: list(client.stream(req(base, '/keepalive'), token)))
            assert entered.wait(2)
            healthy = pool.submit(lambda: list(client.stream(req(base))))
            assert healthy.result(2)[-1]['type'] == 'done'
            token.cancel()
            assert blocked.result(1) == []
        assert not client.transport._calls
    finally:
        release.set()
        client.close()


@pytest.mark.parametrize('body', [b'data: ' + b'x' * (MAX_EVENT + 1),
    b'data: ' + b'x' * (MAX_EVENT // 2) + b'\ndata: ' + b'x' * (MAX_EVENT // 2 + 1)], ids=['long-line', 'long-event'])
def test_oversized_lines_and_unterminated_events_are_bounded(body):
    def handle(request):
        return httpx.Response(200, content=body)
    client = HTTPProviderAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        events = list(client.stream(req('https://example.test')))
        assert events[-1]['error_kind'] == 'protocol'
    finally:
        client.close()


def test_close_active_transport_stops_consumer_and_closes_event_loop(server):
    base, entered, release, _ = server
    client = adapter()
    try:
        with ThreadPoolExecutor() as pool:
            running = pool.submit(lambda: list(client.stream(req(base, '/headers'))))
            assert entered.wait(2)
            client.close()
            assert running.result(3)[-1]['type'] == 'error'
        assert not client.transport._thread.is_alive()
        assert client.transport._loop.is_closed()
    finally:
        release.set()
        client.close()
