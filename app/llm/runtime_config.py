"""Explicit immutable model configuration for headless clients."""
from dataclasses import dataclass, field


def provider_api_type(provider: str, protocol: str = 'auto') -> str:
    """Resolve one explicit wire protocol; there is no SDK fallback route."""
    from app.llm.providers.registry import resolve_protocol
    return resolve_protocol(provider, protocol)


@dataclass(frozen=True)
class GatewayConfig:
    model: str
    provider: str = ''
    base_url: str = ''
    api_key: str = field(default='', repr=False)
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    api_protocol: str = 'auto'
