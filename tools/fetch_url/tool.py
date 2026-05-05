import json
import sys

_MAX_CONTENT = 20_000


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    url = payload.get("params", {}).get("url", "").strip()

    if not url:
        print(json.dumps({"status": "error", "data": {"message": "url is required"}}))
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        if "json" in content_type:
            try:
                body = json.dumps(resp.json(), ensure_ascii=False)[:_MAX_CONTENT]
                print(
                    json.dumps(
                        {"status": "success", "data": {"url": str(resp.url), "type": "json", "content": body}},
                        ensure_ascii=False,
                    )
                )
                return
            except Exception:
                pass

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")

            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
                tag.decompose()

            main_el = (
                soup.find("main")
                or soup.find("article")
                or soup.find(id="content")
                or soup.find(class_="content")
            )
            raw = (main_el or soup).get_text(separator="\n", strip=True)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            text = "\n".join(lines)

            title_el = soup.find("title")
            title = title_el.get_text(strip=True) if title_el else ""

            truncated = len(text) > _MAX_CONTENT
            print(
                json.dumps(
                    {
                        "status": "success",
                        "data": {
                            "url": str(resp.url),
                            "title": title,
                            "type": "html",
                            "content": text[:_MAX_CONTENT],
                            "truncated": truncated,
                            "total_chars": len(text),
                        },
                    },
                    ensure_ascii=False,
                )
            )
        except ImportError:
            text = resp.text[:_MAX_CONTENT]
            print(
                json.dumps(
                    {"status": "success", "data": {"url": str(resp.url), "type": "raw", "content": text}},
                    ensure_ascii=False,
                )
            )

    except Exception as e:
        print(
            json.dumps(
                {"status": "error", "data": {"message": str(e), "url": url}},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
