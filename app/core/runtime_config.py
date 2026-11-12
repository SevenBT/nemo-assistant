"""Explicit immutable model configuration for headless clients."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayConfig:
    model: str
    provider: str = ''
    base_url: str = ''
    api_key: str = field(default='', repr=False)
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
