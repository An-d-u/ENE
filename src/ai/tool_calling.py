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
    match = re.match(r"^/search(?:\s+(.*))?$", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return (match.group(1) or "").strip()


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


class WebSearchToolRunner:
    def __init__(
        self,
        *,
        search_tool: SearchTool | None,
        enabled: bool,
        auto_enabled: bool = True,
        max_results: int = 5,
        decision_provider=None,
        progress_callback=None,
    ):
        self.search_tool = search_tool
        self.enabled = bool(enabled)
        self.auto_enabled = bool(auto_enabled)
        self.max_results = self._coerce_max_results(max_results)
        self.decision_provider = decision_provider
        self.progress_callback = progress_callback

    def _coerce_max_results(self, max_results) -> int:
        try:
            value = 5 if max_results is None else int(max_results)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(value, 10))

    def _emit_progress(self, stage: str) -> None:
        if callable(self.progress_callback):
            self.progress_callback(stage)

    def _search_and_format(self, query: SearchQuery) -> str:
        self._emit_progress("searching")
        try:
            response = self.search_tool.search(query)
        except Exception as error:
            print(f"[WebSearchToolRunner] search failed: {type(error).__name__}")
            return ""
        finally:
            self._emit_progress("thinking")
        return build_search_context_block(response)

    def build_context(
        self,
        *,
        message: str,
        latest_user_message: str = "",
        recent_context: str = "",
        mode: str = "auto",
        manual_query: str = "",
    ) -> str:
        if not self.enabled or self.search_tool is None:
            return ""
        if mode == "manual":
            query_text = str(manual_query or "").strip()
            if not query_text:
                return ""
            return self._search_and_format(SearchQuery(query=query_text, max_results=self.max_results))
        if not self.auto_enabled:
            return ""
        decision = self.decide(latest_user_message or message, recent_context=recent_context)
        if not decision.should_search or not decision.query:
            return ""
        return self._search_and_format(SearchQuery(query=decision.query, max_results=self.max_results))

    def decide(self, latest_user_message: str, recent_context: str = "") -> WebSearchDecision:
        if callable(self.decision_provider):
            return self.decision_provider(latest_user_message, recent_context)
        return WebSearchDecision(False, "", "")

    def parse_decision(self, raw_text: str) -> WebSearchDecision:
        try:
            data = json.loads(str(raw_text or ""))
        except Exception:
            return WebSearchDecision(False, "", "")
        if not isinstance(data, dict):
            return WebSearchDecision(False, "", "")
        return WebSearchDecision(
            should_search=bool(data.get("should_search", False)),
            query=str(data.get("query", "") or "").strip(),
            reason=str(data.get("reason", "") or "").strip(),
        )
