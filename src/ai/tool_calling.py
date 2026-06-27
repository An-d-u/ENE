from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .search_tool import SearchQuery, SearchResponse, SearchTool


@dataclass(frozen=True)
class WebSearchDecision:
    should_search: bool
    query: str = ""
    reason: str = ""


def parse_manual_search_command(message: str) -> str:
    text = str(message or "").strip()
    if not text.lower().startswith("/search"):
        return ""
    return text[len("/search") :].strip()


def build_search_context_block(response: SearchResponse, max_snippet_chars: int = 500) -> str:
    if not response.results:
        return ""
    lines = [
        "[WEB_SEARCH_RESULTS]",
        f"Query: {response.query}",
        f"Provider: {response.provider}",
        "",
    ]
    for index, result in enumerate(response.results, start=1):
        snippet = result.snippet[:max_snippet_chars].strip()
        lines.append(f"{index}. {result.title}")
        lines.append(f"URL: {result.url}")
        if result.published_at:
            lines.append(f"Published: {result.published_at}")
        if snippet:
            lines.append(f"Snippet: {snippet}")
        lines.append("")
    lines.append("[/WEB_SEARCH_RESULTS]")
    return "\n".join(lines).strip()
