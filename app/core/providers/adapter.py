"""One HTTP transport with explicit protocol codecs. No model SDK."""
import httpx

from . import anthropic, chat, cohere, responses
from .errors import _error_event
from .registry import endpoint, resolve_protocol
from .transport import HttpTransport, ProtocolError

CODECS = {'openai_chat': chat, 'responses': responses, 'anthropic_messages': anthropic, 'cohere_chat': cohere}


class HTTPProviderAdapter:
    def __init__(self, client=None, *, transport=None):
        self.transport = transport if transport is not None else HttpTransport(client)

    def close(self):
        self.transport.close()

    def stream(self, request, cancel_token=None):
        usage = None
        if cancel_token and cancel_token.is_cancelled():
            return
        try:
            if not request.api_key:
                raise ValueError(f'{request.provider or "模型"} API Key 未配置')
            protocol = resolve_protocol(request.provider, request.api_protocol)
            codec = CODECS[protocol]
            images = any(isinstance(m.get('content'), list) and any(
                p.get('type') == 'image_url' for p in m['content']) for m in request.messages)
            url = endpoint(request.provider, request.base_url, protocol, images=images)
            headers = {'Accept': 'text/event-stream'}
            if protocol == 'anthropic_messages':
                headers.update({'x-api-key': request.api_key, 'anthropic-version': '2023-06-01'})
            else:
                headers['Authorization'] = f'Bearer {request.api_key}'
            frames = self.transport.stream(url, headers, codec.request_body(request),
                                           cancel_token, request.stream_timeout)
            decoder = codec.decode(frames)
            try:
                for event in decoder:
                    if cancel_token and cancel_token.is_cancelled():
                        return
                    if event['type'] == 'usage':
                        usage = event['usage']
                        continue
                    if event['type'] in ('tool_call', 'done'):
                        frames.close()
                    yield event
            finally:
                decoder.close()
                frames.close()
        except Exception as exc:
            if cancel_token and cancel_token.is_cancelled():
                return
            event = _error_event(exc, f'{request.provider or "模型"} 调用失败')
            if isinstance(exc, ProtocolError):
                event['error_kind'] = 'protocol'
            elif isinstance(exc, ValueError):
                event['error_kind'] = 'configuration'
            elif isinstance(exc, httpx.TransportError) and not event.get('error_kind'):
                event['error_kind'] = 'connection'
            if request.api_key:
                event['message'] = event['message'].replace(request.api_key, '[REDACTED]')
            if usage is not None:
                event['usage'] = usage
            yield event
