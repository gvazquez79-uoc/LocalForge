"""
WebFetch tool — fetch a URL and return its content as clean markdown/text.
Uses html2text to convert HTML → markdown when available,
falls back to raw text stripping otherwise.
"""
from __future__ import annotations

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
        import asyncio
        import re

        max_length = min(max_length, 32000)

        try:
            import httpx
        except ImportError:
            return "Error: httpx not installed. Run: pip install httpx"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; LocalForge/1.0; +https://github.com/localforge)"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15.0,
                headers=headers,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                raw = resp.text
        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code} fetching {url}"
        except httpx.TimeoutException:
            return f"Timeout fetching {url} (>15s)"
        except Exception as e:
            return f"Error fetching {url}: {e}"

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
    """Convert HTML to readable text. Uses html2text if available, otherwise basic strip."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = False
        h.body_width = 0  # don't wrap
        return h.handle(html)
    except ImportError:
        pass

    # Fallback: basic HTML stripping
    import re
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = (text
        .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    )
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


WEB_FETCH_TOOLS: list[BaseTool] = [WebFetchTool()]
