"""One bounded async connection pool behind the application's sync stream API."""
from __future__ import annotations
import asyncio
import queue
import threading
import httpx

TIMEOUT = httpx.Timeout(connect=15, read=120, write=15, pool=15)
MAX_EVENT = 2 * 1024 * 1024
MAX_ERROR = 64 * 1024


class ProtocolError(ValueError):
    pass


class ProviderError(Exception):
    def __init__(self, body, status_code=None, headers=None):
        super().__init__('Provider request failed')
        self.body, self.status_code = body, status_code
        self.response = type('ErrorResponse', (), {'headers': headers or {}})()


class _Call:
    def __init__(self, future, finished):
        self.future, self.finished = future, finished

    def close(self):
        self.future.cancel()


class HttpTransport:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._closed = False
        self._calls = set()

    def _start(self):
        with self._lock:
            if self._closed:
                raise RuntimeError('模型连接池已关闭')
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, name='model-http', daemon=True)
                self._thread.start()
            return self._loop

    def stream(self, url, headers, body, cancel_token=None, timeout=None):
        if cancel_token and cancel_token.is_cancelled():
            return
        loop = self._start()
        output = queue.Queue(maxsize=32)
        finished = threading.Event()
        with self._lock:
            if self._closed:
                raise RuntimeError('模型连接池已关闭')
            future = asyncio.run_coroutine_threadsafe(
                self._read(url, headers, body, output, finished, timeout), loop)
            call = _Call(future, finished)
            self._calls.add(call)
        if cancel_token:
            cancel_token.add_resource(call)
        try:
            while True:
                if cancel_token and cancel_token.is_cancelled():
                    return
                try:
                    item = output.get(timeout=0.05)
                except queue.Empty:
                    if finished.is_set() or future.cancelled():
                        return
                    continue
                if isinstance(item, Exception):
                    raise item
                if item is None:
                    return
                yield item
        finally:
            call.close()
            finished.wait(2)
            if cancel_token:
                cancel_token.remove_resource(call)
            with self._lock:
                self._calls.discard(call)

    async def _read(self, url, headers, body, output, finished, timeout):
        async def put(item):
            while True:
                try:
                    output.put_nowait(item)
                    return
                except queue.Full:
                    await asyncio.sleep(0.01)

        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
            async with asyncio.timeout(timeout):
                async with self._client.stream('POST', url, headers=headers, json=body) as response:
                    if response.status_code >= 300:
                        error = bytearray()
                        async for chunk in response.aiter_bytes():
                            error.extend(chunk[:max(0, MAX_ERROR - len(error))])
                            if len(error) >= MAX_ERROR:
                                break
                        raise ProviderError(error.decode('utf-8', errors='replace'), response.status_code, response.headers)
                    # Split bounded lines ourselves; aiter_lines can buffer an unbounded line.
                    pending = ''
                    data = []
                    event_type = ''
                    size = 0
                    async for chunk in response.aiter_text():
                        pending += chunk
                        while '\n' in pending:
                            line, pending = pending.split('\n', 1)
                            line = line.rstrip('\r')
                            if len(line) > MAX_EVENT:
                                raise ProtocolError('模型响应单行超过限制')
                            if not line:
                                if data:
                                    await put((event_type, '\n'.join(data)))
                                data, event_type, size = [], '', 0
                            elif line.startswith('data:'):
                                value = line[5:].removeprefix(' ')
                                size += len(value)
                                if size > MAX_EVENT:
                                    raise ProtocolError('模型响应事件超过限制')
                                data.append(value)
                            elif line.startswith('event:'):
                                event_type = line[6:].strip()
                        if len(pending) > MAX_EVENT:
                            raise ProtocolError('模型响应单行超过限制')
                    if pending.startswith('data:'):
                        value = pending[5:].removeprefix(' ').rstrip('\r')
                        if size + len(value) > MAX_EVENT:
                            raise ProtocolError('模型响应事件超过限制')
                        data.append(value)
                    if data:
                        await put((event_type, '\n'.join(data)))
            await put(None)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await put(httpx.ReadTimeout('模型调用超过总时限'))
        except Exception as exc:
            await put(exc)
        finally:
            finished.set()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, thread, calls = self._loop, self._thread, list(self._calls)
        if loop is None:
            if self._client is not None:
                asyncio.run(self._client.aclose())
            return
        for call in calls:
            call.close()
        async def shutdown():
            current = asyncio.current_task()
            tasks = [t for t in asyncio.all_tasks() if t is not current]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._client is not None:
                await self._client.aclose()
        try:
            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=3)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(3)
            if not thread.is_alive():
                loop.close()
