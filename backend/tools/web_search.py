"""
Web search tool using DuckDuckGo (no API key required).
"""
from __future__ import annotations

from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo and return a list of results with titles, "
        "URLs, and snippets. No API key required."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, max_results: int | None = None, **_: Any) -> str:
        cfg = get_config().tools.web_search
        limit = min(max_results or cfg.max_results, 10)

        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=limit):
                    results.append(r)

            if not results:
                return f"No results found for: {query}"

            lines = [f"Search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", "")
                body = r.get("body", "")[:200].replace("\n", " ")
                lines.append(f"{i}. {title}\n   URL: {url}\n   {body}\n")

            return "\n".join(lines)

        except ImportError:
            return "Error: duckduckgo-search package not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            return f"Search error: {e}"


WEB_SEARCH_TOOLS: list[BaseTool] = [WebSearchTool()]
