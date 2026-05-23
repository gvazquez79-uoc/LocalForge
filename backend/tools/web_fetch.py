"""
WebFetch tool — fetch a URL and return its content as clean markdown/text.
Uses html2text to convert HTML → markdown when available,
falls back to raw text stripping otherwise.
"""
from __future__ import annotations

import re

from backend.tools.base import BaseTool


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch the content of a URL and return it as readable text/markdown. "
        "Use this to read documentation, GitHub issues, articles, API references, or any web page. "
        "Different from web_search — this reads a SPECIFIC URL, not a search query."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL to fetch, e.g. 'https://docs.python.org/3/library/asyncio.html'",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return (default 8000, max 32000).",
            },
        },
        "required": ["url"],
    }

    async def run(self, url: str, max_length: int = 8000) -> str:
        max_length = min(max_length, 32000)

        try:
            import httpx
        except ImportError:
            return "Error: httpx not installed. Run: pip install httpx"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

        # Try with system SSL first; fall back to verify=False on SSL errors (Windows certs)
        for verify in (True, False):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=15.0,
                    headers=headers,
                    verify=verify,
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    raw = resp.text
                break  # success
            except httpx.HTTPStatusError as e:
                return f"HTTP error {e.response.status_code} fetching {url}"
            except httpx.TimeoutException:
                return f"Timeout fetching {url} (>15s)"
            except Exception as e:
                if verify and "SSL" in str(e):
                    continue  # retry without SSL verification
                return f"Error fetching {url}: {e}"
        else:
            return f"Error fetching {url}: SSL verification failed"

        # Convert HTML → markdown if possible
        if "html" in content_type or raw.lstrip().startswith("<"):
            text = _html_to_text(raw)
        else:
            text = raw

        # Trim to max_length
        if len(text) > max_length:
            text = text[:max_length] + f"\n\n… [truncated — {len(text) - max_length} more chars]"

        return f"# {url}\n\n{text.strip()}"


def _html_to_text(html: str) -> str:
    """Convert HTML to readable text.
    Pipeline: BeautifulSoup (extract main content) → html2text (clean markdown).
    Falls back to regex stripping if neither is available.
    """
    # Step 1: extract main content block with BeautifulSoup to reduce noise
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
            tag.decompose()
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id=re.compile(r"(content|main|article)", re.I))
            or soup.find(class_=re.compile(r"(content|main|article|post|entry)", re.I))
            or soup.body
            or soup
        )
        html = str(main)
    except ImportError:
        pass  # no bs4 — feed raw HTML to html2text

    # Step 2: convert to markdown/text
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = False
        h.body_width = 0
        h.unicode_snob = True
        return h.handle(html)
    except ImportError:
        pass

    # Final fallback: basic regex stripping
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text
        .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


WEB_FETCH_TOOLS: list[BaseTool] = [WebFetchTool()]
