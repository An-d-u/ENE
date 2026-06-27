from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import requests


def _coerce_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(min_value, min(coerced, max_value))


@dataclass(frozen=True)
class SearchQuery:
    query: str
    max_results: int = 5
    time_range: str = ""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class SearchResponse:
    query: str
    provider: str
    results: list[SearchResult] = field(default_factory=list)


class SearchProvider(Protocol):
    provider_name: str

    def search(self, query: SearchQuery) -> SearchResponse:
        ...


class TavilySearchProvider:
    provider_name = "tavily"

    def __init__(self, api_key: str, timeout_sec: int = 12):
        self.api_key = str(api_key or "").strip()
        self.timeout_sec = _coerce_int(timeout_sec, default=12, min_value=1, max_value=60)

    def search(self, query: SearchQuery) -> SearchResponse:
        if not self.api_key:
            return SearchResponse(query=query.query, provider=self.provider_name, results=[])
        payload = {
            "query": query.query,
            "max_results": _coerce_int(query.max_results, default=5, min_value=1, max_value=10),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        if query.time_range:
            payload["time_range"] = query.time_range
        response = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "") or "").strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title", "") or "").strip() or url,
                    url=url,
                    snippet=str(item.get("content", "") or item.get("snippet", "") or "").strip(),
                    published_at=str(item.get("published_date", "") or item.get("published_at", "") or "").strip(),
                )
            )
        return SearchResponse(
            query=str(data.get("query", query.query) or query.query),
            provider=self.provider_name,
            results=results,
        )


class SearchTool:
    def __init__(self, provider: SearchProvider):
        self.provider = provider

    def search(self, query: SearchQuery) -> SearchResponse:
        try:
            return self.provider.search(query)
        except Exception as error:
            provider_name = getattr(self.provider, "provider_name", "unknown")
            print(f"[SearchTool] search failed: provider={provider_name} error_type={type(error).__name__}")
            return SearchResponse(
                query=query.query,
                provider=provider_name,
                results=[],
            )
