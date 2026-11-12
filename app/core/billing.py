"""Provider-reported charges and safe console links; no local price estimates."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from urllib.parse import urlsplit

# Only link known official endpoints. A compatible proxy has its own billing.
_CONSOLES = {
    "deepseek": ("https://platform.deepseek.com/", {"api.deepseek.com"}),
    "openai": ("https://platform.openai.com/usage", {"api.openai.com"}),
    "anthropic": ("https://console.anthropic.com/", {"api.anthropic.com"}),
    "gemini": ("https://aistudio.google.com/", {"generativelanguage.googleapis.com"}),
    "dashscope": ("https://bailian.console.aliyun.com/", {
        "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    }),
    "zai": ("https://z.ai/", {"api.z.ai"}),
}


def billing_url_for(provider: str, base_url: str = "") -> str | None:
    console = _CONSOLES.get(provider)
    if console is None:
        return None
    if base_url:
        try:
            url = urlsplit(base_url)
            if (url.scheme != "https" or url.hostname not in console[1]
                    or url.username or url.password or url.port not in (None, 443)):
                return None
        except ValueError:
            return None
    return console[0]


def validate_billing_url(provider: str, value) -> str | None:
    """Never persist/open an arbitrary URL supplied in a response or old DB."""
    expected = billing_url_for(provider)
    return expected if expected and value == expected else None


def normalize_provider_cost(value) -> dict | None:
    """Adapter contract: an explicit provider charge, never SDK _response_cost.

    Adapters may emit provider_cost={amount, currency} only for a documented
    upstream charge field. Estimated SDK costs and prices must not use it.
    """
    if not isinstance(value, dict):
        return None
    amount, currency = value.get("amount"), value.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str, Decimal)):
        return None
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        number = Decimal(str(amount))
        if not number.is_finite() or number < 0:
            return None
        number = float(number)
        if not math.isfinite(number):
            return None
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return {"amount": number, "currency": currency}
