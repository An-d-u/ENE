from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import requests


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
        self.timeout_sec = max(1, int(timeout_sec or 12))

    def search(self, query: SearchQuery) -> SearchResponse:
        if not self.api_key:
            return SearchResponse(query=query.query, provider=self.provider_name, results=[])
        payload = {
            "query": query.query,
            "max_results": max(1, min(int(query.max_results or 5), 10)),
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
            print(f"[SearchTool] search failed: {error}")
            return SearchResponse(
                query=query.query,
                provider=getattr(self.provider, "provider_name", "unknown"),
                results=[],
            )
