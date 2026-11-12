"""Desktop configuration adapters, loaded only by desktop callers."""
from app.core.runtime_config import GatewayConfig


def gateway_config(proxy=None) -> GatewayConfig:
    from app.core.config import cfg, get_litellm_provider_api_key

    model = getattr(proxy, 'litellm_default_model', None) or cfg.get(cfg.litellmDefaultModel)
    lookup = getattr(proxy, 'get_litellm_model_by_id', None)
    model_config = lookup(model) if lookup else None
    if not model_config:
        model_config = next((m for m in cfg.get(cfg.litellmModels) if m.get('id') == model), {})
    provider = model_config.get('provider', '')
    return GatewayConfig(
        model=model, provider=provider, base_url=model_config.get('api_base', ''),
        api_key=get_litellm_provider_api_key(provider) if provider else '',
        max_tokens=cfg.get(cfg.maxTokens), temperature=cfg.get(cfg.temperature),
        top_p=cfg.get(cfg.topP),
    )
