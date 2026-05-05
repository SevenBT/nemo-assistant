import json
import sys
import urllib.parse


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    query = params.get("query", "").strip()
    count = min(int(params.get("count", 5)), 10)
    provider = params.get("provider", "ddg").lower().strip()
    api_key = params.get("api_key", "").strip()

    if not query:
        print(json.dumps({"status": "error", "data": {"message": "query is required"}}))
        return

    try:
        if provider == "bing" and api_key:
            results = _search_bing(query, count, api_key)
        elif provider == "tavily" and api_key:
            results = _search_tavily(query, count, api_key)
        elif provider == "brave" and api_key:
            results = _search_brave(query, count, api_key)
        else:
            results = _search_ddg(query, count)
            provider = "ddg"

        print(
            json.dumps(
                {
                    "status": "success",
                    "data": {"query": query, "provider": provider, "results": results},
                },
                ensure_ascii=False,
            )
        )
    except Exception as e:
        print(
            json.dumps(
                {"status": "error", "data": {"message": str(e)}},
                ensure_ascii=False,
            )
        )


def _search_bing(query: str, count: int, api_key: str) -> list[dict]:
    import httpx

    resp = httpx.get(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": api_key},
        params={"q": query, "count": count, "mkt": "zh-CN", "textFormat": "Raw"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": item.get("name", ""), "url": item.get("url", ""), "snippet": item.get("snippet", "")}
        for item in data.get("webPages", {}).get("value", [])[:count]
    ]


def _search_tavily(query: str, count: int, api_key: str) -> list[dict]:
    import httpx

    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": count, "include_raw_content": False},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")}
        for item in data.get("results", [])[:count]
    ]


def _search_brave(query: str, count: int, api_key: str) -> list[dict]:
    import httpx

    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key},
        params={"q": query, "count": count, "search_lang": "zh"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("description", "")}
        for item in data.get("web", {}).get("results", [])[:count]
    ]


def _search_ddg(query: str, count: int) -> list[dict]:
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": "cn-zh"},
        headers=headers,
        timeout=15,
        follow_redirects=True,
    )

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [
            {
                "title": f"搜索: {query}",
                "url": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
                "snippet": "请安装 beautifulsoup4 以解析搜索结果: pip install beautifulsoup4",
            }
        ]

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict] = []
    for r in soup.select(".result"):
        title_el = r.select_one("h2 a") or r.select_one(".result__title a")
        snippet_el = r.select_one(".result__snippet")
        url_el = r.select_one(".result__url")

        if not title_el:
            continue

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

        results.append(
            {
                "title": title_el.get_text(strip=True),
                "url": actual_url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
        if len(results) >= count:
            break

    return results


if __name__ == "__main__":
    main()
