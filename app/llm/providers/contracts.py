from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol
from app.llm.cancellation import CancellationToken

@dataclass(frozen=True)
class LLMRequest:
    """网关内部的统一请求对象。

    上层只关心 messages/tools；网关在这里补齐 provider、model、key、
    base_url 等调用细节，再交给具体 adapter。
    """

    trace_id: str
    attempt_id: str
    api_type: str
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    provider: str = ""
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    stream_timeout: float | None = None
    api_protocol: str = "auto"


class ProviderAdapter(Protocol):
    """Provider 适配器协议。

    每个供应商只负责把自己的响应翻译成统一事件，不处理全局限流、
    重试和日志，这些横切逻辑留在 LLMGateway。
    """

    def stream(
        self,
        request: LLMRequest,
        cancel_token: CancellationToken | None = None,
    ) -> Iterator[dict]:
        """Yield normalized gateway events."""
