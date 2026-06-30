"""
网页搜索工具 — 支持多搜索引擎后端。

支持的搜索引擎：
  - DuckDuckGo: 免费，无需 API Key（通过 HTML 解析实现）
  - Bing Search: 需要 Azure API Key
  - Tavily: 需要 Tavily API Key（AI 优化的搜索）
  - Brave Search: 需要 Brave API Key
  - 博查 AI 搜索: 需要博查 API Key（支持 AI 摘要、时间范围、站点过滤）

搜索引擎选择逻辑：
  优先使用用户配置的引擎 + API Key，如果 Key 为空则回退到 DuckDuckGo。

依赖注入：
  通过 create(ctx) 从配置中读取 searchProvider 和 API Key。
"""
from __future__ import annotations

import urllib.parse
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Bool, Num, Str, tool_params
from app.i18n import t

if TYPE_CHECKING:
    from app.tools.context import ToolContext


class WebSearchTool(BuiltinTool):
    """多引擎网页搜索工具。"""

    def __init__(self, provider: str, api_key: str, timeout: int = 15):
        self._provider = provider
        self._api_key = api_key
        self._timeout = timeout

    @classmethod
    def create(cls, ctx: "ToolContext") -> "WebSearchTool":
        """从配置中读取搜索引擎类型和 API Key。"""
        from app.core.config import cfg, get_search_api_key
        return cls(
            provider=cfg.get(cfg.searchProvider),
            api_key=get_search_api_key(),
            timeout=ctx.http_timeout,
        )

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return t("tool.web_search.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "query",  # query 是唯一必填参数
            query=Str(t("tool.web_search.param.query")),
            count=Num(t("tool.web_search.param.count")),
            summary=Bool(t("tool.web_search.param.summary")),
            freshness=Str(t("tool.web_search.param.freshness")),
            include=Str(t("tool.web_search.param.include")),
            exclude=Str(t("tool.web_search.param.exclude")),
        )

    @property
    def read_only(self) -> bool:
        """搜索是只读操作，可并发执行。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        import httpx

        query = params.get("query", "").strip()
        count = min(int(params.get("count", 5)), 10)
        summary = params.get("summary", False)
        freshness = params.get("freshness", "noLimit")
        include = params.get("include", "").strip()
        exclude = params.get("exclude", "").strip()

        if not query:
            return {"status": "error", "data": {"message": "query is required"}}

        provider = self._provider
        api_key = self._api_key

        try:
            # 根据配置的引擎和 Key 选择搜索后端
            if provider == "bing" and api_key:
                results = self._search_bing(query, count, api_key)
            elif provider == "tavily" and api_key:
                results = self._search_tavily(query, count, api_key)
            elif provider == "brave" and api_key:
                results = self._search_brave(query, count, api_key)
            elif provider == "bocha" and api_key:
                results = self._search_bocha(query, count, api_key, summary, freshness, include, exclude)
            else:
                # 无 Key 或未知引擎，回退到免费的 DuckDuckGo
                results = self._search_ddg(query, count)
                provider = "ddg"

            return {"status": "success", "data": {"query": query, "provider": provider, "results": results}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    # ── 各搜索引擎的具体实现 ──

    def _search_bing(self, query: str, count: int, api_key: str) -> list[dict]:
        """Bing Search API v7。"""
        import httpx
        resp = httpx.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": query, "count": count, "mkt": "zh-CN", "textFormat": "Raw"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("name", ""), "url": item.get("url", ""), "snippet": item.get("snippet", "")}
            for item in data.get("webPages", {}).get("value", [])[:count]
        ]

    def _search_tavily(self, query: str, count: int, api_key: str) -> list[dict]:
        """Tavily Search API（AI 优化搜索）。"""
        import httpx
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": count, "include_raw_content": False},
            timeout=self._timeout + 5,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")}
            for item in data.get("results", [])[:count]
        ]

    def _search_brave(self, query: str, count: int, api_key: str) -> list[dict]:
        """Brave Search API。"""
        import httpx
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key},
            params={"q": query, "count": count, "search_lang": "zh"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("description", "")}
            for item in data.get("web", {}).get("results", [])[:count]
        ]

    def _search_bocha(self, query: str, count: int, api_key: str,
                      summary: bool, freshness: str, include: str, exclude: str) -> list[dict]:
        """博查 AI 搜索 API — 支持 AI 摘要、时间范围、站点过滤。"""
        import httpx
        payload: dict[str, Any] = {"query": query, "count": min(count, 50)}
        if summary:
            payload["summary"] = True
        if freshness != "noLimit":
            payload["freshness"] = freshness
        if include:
            payload["include"] = include
        if exclude:
            payload["exclude"] = exclude

        resp = httpx.post(
            "https://api.bocha.cn/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self._timeout + 5,
        )

        # 博查特有的错误码处理
        if resp.status_code == 403:
            raise Exception(t("tool.web_search.msg.bocha_insufficient_balance"))
        elif resp.status_code == 401:
            raise Exception(t("tool.web_search.msg.bocha_invalid_key"))
        elif resp.status_code == 429:
            raise Exception(t("tool.web_search.msg.bocha_rate_limit"))
        elif not resp.is_success:
            raise Exception(t("tool.web_search.msg.bocha_http_error", code=resp.status_code, text=resp.text))

        data = resp.json()
        if data.get("code") != 200:
            raise Exception(t("tool.web_search.msg.bocha_api_error", msg=data.get('msg', t("tool.web_search.msg.unknown_error"))))

        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
        return [
            {
                "title": page.get("name", ""),
                "url": page.get("url", ""),
                "snippet": page.get("snippet", ""),
                "summary": page.get("summary", ""),
                "site_name": page.get("siteName", ""),
                "date_published": page.get("datePublished", ""),
            }
            for page in web_pages[:count]
        ]

    def _search_ddg(self, query: str, count: int) -> list[dict]:
        """DuckDuckGo 搜索（免费，通过 HTML 解析实现）。"""
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "cn-zh"},
            headers=headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return [{"title": t("tool.web_search.msg.ddg_search", query=query), "url": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
                     "snippet": t("tool.web_search.msg.install_bs4")}]

        # 解析 DuckDuckGo HTML 搜索结果页
        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[dict] = []
        for r in soup.select(".result"):
            title_el = r.select_one("h2 a") or r.select_one(".result__title a")
            snippet_el = r.select_one(".result__snippet")
            url_el = r.select_one(".result__url")
            if not title_el:
                continue
            # 从 DuckDuckGo 的重定向链接中提取真实 URL
            href = title_el.get("href", "")
            actual_url = ""
            if "uddg=" in href:
                try:
                    actual_url = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass
            if not actual_url and url_el:
                url_text = url_el.get_text(strip=True)
                actual_url = ("https://" + url_text) if not url_text.startswith("http") else url_text
            if not actual_url:
                continue
            results.append({
                "title": title_el.get_text(strip=True),
                "url": actual_url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })
            if len(results) >= count:
                break
        return results
