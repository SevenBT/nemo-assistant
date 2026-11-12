"""Versioned protocol/endpoint profiles with no desktop dependencies."""
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    base_url: str
    protocol: str = 'openai_chat'
    revision: int = 1


PROFILES = {p.id: p for p in (
    ProviderProfile('deepseek', 'https://api.deepseek.com'),
    ProviderProfile('openai', 'https://api.openai.com/v1'),
    ProviderProfile('anthropic', 'https://api.anthropic.com/v1', 'anthropic_messages'),
    ProviderProfile('gemini', 'https://generativelanguage.googleapis.com/v1beta/openai'),
    ProviderProfile('dashscope', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    ProviderProfile('zai', 'https://api.z.ai/api/paas/v4'),
    ProviderProfile('meta_llama', 'https://api.llama.com/compat/v1'),
    ProviderProfile('cohere', 'https://api.cohere.com/v2', 'cohere_chat'),
)}
PROTOCOL_PATHS = {'openai_chat': '/chat/completions', 'responses': '/responses',
                  'anthropic_messages': '/messages', 'cohere_chat': '/chat'}


def resolve_protocol(provider: str, protocol: str = 'auto') -> str:
    if protocol != 'auto':
        if protocol not in PROTOCOL_PATHS:
            raise ValueError('不支持的模型接口协议，请检查模型的 API 协议设置')
        return protocol
    return PROFILES.get(provider, ProviderProfile(provider, '')).protocol


def endpoint(provider: str, base_url: str, protocol: str, *, images: bool = False) -> str:
    profile = PROFILES.get(provider)
    base = base_url or (profile.base_url if profile else '')
    if not base:
        raise ValueError(f'{provider or "自定义服务"} 需要明确配置 API 地址和协议')
    if provider == 'deepseek' and images and not base_url:
        base += '/beta'
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('模型 API 地址无效，不允许内嵌账号、查询参数或片段')
    _ = url.port
    if provider == 'azure':
        if '/deployments/' in url.path:
            raise ValueError('Azure 请使用资源根地址或 /openai/v1，并将 Model ID 设置为部署名称')
        if not url.path.strip('/'):
            base = base.rstrip('/') + '/openai/v1'
        elif url.path.rstrip('/') == '/openai':
            base = base.rstrip('/') + '/v1'
    if provider == 'gemini' and protocol == 'openai_chat' and url.hostname == 'generativelanguage.googleapis.com':
        if url.path.rstrip('/') in ('', '/v1', '/v1beta'):
            base = base.rstrip('/') + ('/v1beta' if not url.path.strip('/') else '') + '/openai'
    suffix = PROTOCOL_PATHS[protocol]
    path = urlsplit(base).path.rstrip('/')
    for other in PROTOCOL_PATHS.values():
        if path.endswith(other) and other != suffix:
            raise ValueError('API 地址与所选协议不一致，请检查模型高级设置')
    return base.rstrip('/') if path.endswith(suffix) else base.rstrip('/') + suffix
