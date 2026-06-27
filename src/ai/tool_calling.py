from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .search_tool import SearchQuery, SearchResponse, SearchTool, TavilySearchProvider


@dataclass(frozen=True)
class WebSearchDecision:
    should_search: bool
    query: str = ""
    reason: str = ""


def build_web_search_decision_prompt(latest_user_message: str, recent_context: str = "") -> str:
    payload = {
        "latest_user_message": str(latest_user_message or "").strip(),
        "recent_context": str(recent_context or "").strip(),
    }
    return (
        "Decide whether the assistant should use web search before answering.\n"
        "Return a JSON object only, with these fields: should_search, query, reason.\n"
        "\n"
        "Search when the user asks for current or changeable information, including news, prices, schedules, "
        "laws or regulations, product specifications or availability, sports scores, market data, or other facts "
        "that may have changed recently.\n"
        "Do not search for personal advice, creative writing, code explanation, summarization, or requests that can "
        "be answered from the current conversation context.\n"
        "If searching, make query a short neutral search-engine query. Do not include unnecessary private context, "
        "personal data, or sensitive details.\n"
        "\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _strip_json_fence(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_web_search_decision(raw_text: str) -> WebSearchDecision:
    try:
        data = json.loads(_strip_json_fence(raw_text))
    except Exception:
        return WebSearchDecision(False, "", "")
    if not isinstance(data, dict):
        return WebSearchDecision(False, "", "")

    should_search = data.get("should_search", False)
    if isinstance(should_search, str):
        should_search = should_search.strip().lower() in {"true", "1", "yes"}
    else:
        should_search = bool(should_search)

    query = str(data.get("query", "") or "").strip()
    reason = str(data.get("reason", "") or "").strip()
    if should_search and not query:
        return WebSearchDecision(False, "", "")
    return WebSearchDecision(should_search=should_search, query=query, reason=reason)


def create_web_search_decision_provider(generate_text):
    def _provider(latest_user_message: str, recent_context: str = "") -> WebSearchDecision:
        if not callable(generate_text):
            return WebSearchDecision(False, "", "")
        prompt = build_web_search_decision_prompt(latest_user_message, recent_context)
        try:
            raw_text = generate_text(prompt)
        except Exception:
            return WebSearchDecision(False, "", "")
        return _parse_web_search_decision(raw_text)

    return _provider


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


def _read_setting(settings, key: str, default=None):
    if settings is None:
        return default
    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            return default
    if isinstance(settings, dict):
        return settings.get(key, default)
    config = getattr(settings, "config", None)
    if isinstance(config, dict) and key in config:
        return config.get(key, default)
    return getattr(settings, key, default)


def _read_web_search_api_key(settings, provider: str) -> str:
    keys = _read_setting(settings, "web_search_api_keys", {}) or {}
    if not isinstance(keys, dict):
        return ""
    return str(keys.get(provider, "") or "").strip()


def create_web_search_tool_runner(settings, progress_callback=None, decision_provider=None) -> "WebSearchToolRunner":
    enabled = bool(_read_setting(settings, "web_search_enabled", False))
    auto_enabled = bool(_read_setting(settings, "web_search_auto_enabled", True))
    provider_name = str(_read_setting(settings, "web_search_provider", "tavily") or "tavily").strip().lower()
    max_results = _read_setting(settings, "web_search_max_results", 5)
    timeout_sec = _read_setting(settings, "web_search_timeout_sec", 12)

    search_tool = None
    if enabled and provider_name == "tavily":
        api_key = _read_web_search_api_key(settings, "tavily")
        if api_key:
            search_tool = SearchTool(TavilySearchProvider(api_key=api_key, timeout_sec=timeout_sec))

    return WebSearchToolRunner(
        search_tool=search_tool,
        enabled=enabled,
        auto_enabled=auto_enabled,
        max_results=max_results,
        decision_provider=decision_provider,
        progress_callback=progress_callback,
    )


def build_web_search_context_from_settings(
    settings,
    *,
    message: str,
    latest_user_message: str = "",
    recent_context: str = "",
    progress_callback=None,
    decision_provider=None,
) -> str:
    runner = create_web_search_tool_runner(
        settings,
        progress_callback=progress_callback,
        decision_provider=decision_provider,
    )
    manual_query = parse_manual_search_command(latest_user_message)
    if manual_query:
        return runner.build_context(
            message=message,
            latest_user_message=latest_user_message,
            recent_context=recent_context,
            mode="manual",
            manual_query=manual_query,
        )
    return runner.build_context(
        message=message,
        latest_user_message=latest_user_message,
        recent_context=recent_context,
        mode="auto",
    )


def compose_contextual_message(
    message: str,
    *,
    memory_context: str = "",
    web_search_context: str = "",
) -> str:
    blocks = [
        str(memory_context or "").strip(),
        str(web_search_context or "").strip(),
        str(message or ""),
    ]
    return "\n\n".join(block for block in blocks if block)


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
            try:
                self.progress_callback(stage)
            except Exception:
                return

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
            try:
                return self.decision_provider(latest_user_message, recent_context)
            except Exception:
                return WebSearchDecision(False, "", "")
        return WebSearchDecision(False, "", "")

    def parse_decision(self, raw_text: str) -> WebSearchDecision:
        return _parse_web_search_decision(raw_text)
