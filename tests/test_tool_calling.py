from src.ai.search_tool import SearchResponse, SearchResult
from src.ai.tool_calling import (
    WebSearchDecision,
    WebSearchToolRunner,
    build_web_search_context_from_settings,
    create_web_search_decision_provider,
    build_search_context_block,
    create_web_search_tool_runner,
    parse_manual_search_command,
)


class DummySearchTool:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return SearchResponse(
            query=query.query,
            provider="dummy",
            results=[SearchResult(title="Result", url="https://example.com", snippet="Neutral snippet.")],
        )


class DummySettings:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_build_search_context_block_formats_results_with_sources():
    response = SearchResponse(
        query="release notes",
        provider="tavily",
        results=[
            SearchResult(
                title="Release Notes",
                url="https://example.com/release",
                snippet="A short neutral summary.",
                published_at="2026-06-20",
            )
        ],
    )

    block = build_search_context_block(response)

    assert "[WEB_SEARCH_RESULTS]" in block
    assert "Query: release notes" in block
    assert "Provider: tavily" in block
    assert "1. Release Notes" in block
    assert "URL: https://example.com/release" in block
    assert "Published: 2026-06-20" in block
    assert "Snippet: A short neutral summary." in block
    assert "[/WEB_SEARCH_RESULTS]" in block


def test_build_search_context_block_returns_empty_for_no_results():
    response = SearchResponse(query="release notes", provider="tavily", results=[])

    assert build_search_context_block(response) == ""


def test_parse_manual_search_command_extracts_query():
    assert parse_manual_search_command("/search Tavily pricing") == "Tavily pricing"
    assert parse_manual_search_command(" /search   release notes  ") == "release notes"
    assert parse_manual_search_command("hello") == ""
    assert parse_manual_search_command("/searching Tavily pricing") == ""
    assert parse_manual_search_command("/search") == ""


def test_web_search_runner_uses_manual_search_query_without_decision():
    tool = DummySearchTool()
    runner = WebSearchToolRunner(search_tool=tool, enabled=True, auto_enabled=False, max_results=4)

    block = runner.build_context(
        message="/search neutral topic",
        latest_user_message="/search neutral topic",
        recent_context="private context that should not be searched",
        mode="manual",
        manual_query="neutral topic",
    )

    assert tool.queries[0].query == "neutral topic"
    assert tool.queries[0].max_results == 4
    assert "private context" not in tool.queries[0].query
    assert "[WEB_SEARCH_RESULTS]" in block


def test_create_web_search_tool_runner_from_settings_uses_tavily_provider(monkeypatch):
    class FakeTavilyProvider:
        provider_name = "tavily"

        def __init__(self, api_key, timeout_sec=12):
            self.api_key = api_key
            self.timeout_sec = timeout_sec

        def search(self, query):
            return SearchResponse(
                query=query.query,
                provider=self.provider_name,
                results=[
                    SearchResult(
                        title="Neutral Result",
                        url="https://example.com/neutral",
                        snippet="Synthetic neutral snippet.",
                    )
                ],
            )

    monkeypatch.setattr("src.ai.tool_calling.TavilySearchProvider", FakeTavilyProvider)
    settings = DummySettings(
        {
            "web_search_enabled": True,
            "web_search_auto_enabled": False,
            "web_search_provider": "tavily",
            "web_search_max_results": 3,
            "web_search_timeout_sec": 9,
            "web_search_api_keys": {"tavily": "synthetic-key"},
        }
    )

    runner = create_web_search_tool_runner(settings)
    block = runner.build_context(
        message="/search neutral topic",
        latest_user_message="/search neutral topic",
        mode="manual",
        manual_query="neutral topic",
    )

    assert runner.max_results == 3
    assert "[WEB_SEARCH_RESULTS]" in block
    assert "Query: neutral topic" in block
    assert "Synthetic neutral snippet." in block


def test_create_web_search_tool_runner_returns_safe_empty_runner_for_missing_key():
    settings = DummySettings(
        {
            "web_search_enabled": True,
            "web_search_auto_enabled": True,
            "web_search_provider": "tavily",
            "web_search_api_keys": {"tavily": ""},
        }
    )

    runner = create_web_search_tool_runner(settings)
    block = runner.build_context(
        message="/search neutral topic",
        latest_user_message="/search neutral topic",
        mode="manual",
        manual_query="neutral topic",
    )

    assert block == ""


def test_web_search_runner_skips_when_disabled():
    tool = DummySearchTool()
    runner = WebSearchToolRunner(search_tool=tool, enabled=False, auto_enabled=True)

    assert runner.build_context(message="latest price?", latest_user_message="latest price?") == ""
    assert tool.queries == []


def test_web_search_runner_emits_search_progress_during_manual_search():
    tool = DummySearchTool()
    stages = []
    runner = WebSearchToolRunner(
        search_tool=tool,
        enabled=True,
        auto_enabled=False,
        progress_callback=stages.append,
    )

    runner.build_context(
        message="/search neutral topic",
        latest_user_message="/search neutral topic",
        mode="manual",
        manual_query="neutral topic",
    )

    assert stages == ["searching", "thinking"]


def test_web_search_runner_restores_thinking_when_search_raises():
    class RaisingSearchTool:
        def search(self, query):
            raise RuntimeError("synthetic failure")

    stages = []
    runner = WebSearchToolRunner(
        search_tool=RaisingSearchTool(),
        enabled=True,
        auto_enabled=False,
        progress_callback=stages.append,
    )

    block = runner.build_context(
        message="/search neutral topic",
        mode="manual",
        manual_query="neutral topic",
    )

    assert block == ""
    assert stages == ["searching", "thinking"]


def test_web_search_runner_ignores_decision_provider_failure_without_searching():
    def raising_decision_provider(latest_user_message, recent_context):
        raise RuntimeError("synthetic failure")

    tool = DummySearchTool()
    runner = WebSearchToolRunner(
        search_tool=tool,
        enabled=True,
        auto_enabled=True,
        decision_provider=raising_decision_provider,
    )

    block = runner.build_context(
        message="neutral current question",
        latest_user_message="neutral current question",
        recent_context="private context that should not be logged",
    )

    assert block == ""
    assert tool.queries == []


def test_web_search_runner_returns_manual_results_when_progress_callback_raises():
    stages = []

    def raising_progress_callback(stage):
        stages.append(stage)
        raise RuntimeError("synthetic failure")

    tool = DummySearchTool()
    runner = WebSearchToolRunner(
        search_tool=tool,
        enabled=True,
        auto_enabled=False,
        progress_callback=raising_progress_callback,
    )

    block = runner.build_context(
        message="/search neutral topic",
        mode="manual",
        manual_query="neutral topic",
    )

    assert tool.queries[0].query == "neutral topic"
    assert stages == ["searching", "thinking"]
    assert "[WEB_SEARCH_RESULTS]" in block


def test_web_search_runner_parses_structured_decision_json():
    runner = WebSearchToolRunner(search_tool=None, enabled=True)

    decision = runner.parse_decision('{"should_search": true, "query": "neutral query", "reason": "current info"}')

    assert decision.should_search is True
    assert decision.query == "neutral query"
    assert decision.reason == "current info"


def test_web_search_runner_ignores_malformed_decision_json():
    runner = WebSearchToolRunner(search_tool=None, enabled=True)

    decision = runner.parse_decision("not json")

    assert decision == WebSearchDecision(False, "", "")


def test_web_search_decision_provider_parses_fenced_whitespace_json():
    calls = []

    def generate_text(prompt):
        calls.append(prompt)
        return """
        ```json
        {"should_search": true, "query": "neutral product release date", "reason": "current info"}
        ```
        """

    provider = create_web_search_decision_provider(generate_text)

    decision = provider("What is the latest release date?", "Earlier neutral context.")

    assert len(calls) == 1
    assert "latest_user_message" in calls[0]
    assert decision == WebSearchDecision(True, "neutral product release date", "current info")


def test_web_search_decision_provider_falls_back_for_malformed_and_exception():
    malformed_provider = create_web_search_decision_provider(lambda prompt: "not json")

    def raising_generate_text(prompt):
        raise RuntimeError("synthetic failure")

    raising_provider = create_web_search_decision_provider(raising_generate_text)

    assert malformed_provider("latest neutral question", "") == WebSearchDecision(False, "", "")
    assert raising_provider("latest neutral question", "") == WebSearchDecision(False, "", "")


def test_build_web_search_context_does_not_call_decision_for_manual_mode(monkeypatch):
    class FakeTavilyProvider:
        provider_name = "tavily"

        def __init__(self, api_key, timeout_sec=12):
            self.api_key = api_key
            self.timeout_sec = timeout_sec

        def search(self, query):
            return SearchResponse(
                query=query.query,
                provider=self.provider_name,
                results=[
                    SearchResult(
                        title="Neutral Result",
                        url="https://example.com/neutral",
                        snippet="Synthetic neutral snippet.",
                    )
                ],
            )

    calls = []
    settings = DummySettings(
        {
            "web_search_enabled": True,
            "web_search_auto_enabled": True,
            "web_search_provider": "tavily",
            "web_search_api_keys": {"tavily": "synthetic-key"},
        }
    )

    def decision_provider(latest_user_message, recent_context):
        calls.append((latest_user_message, recent_context))
        return WebSearchDecision(True, "should not run", "")

    monkeypatch.setattr("src.ai.tool_calling.TavilySearchProvider", FakeTavilyProvider)
    block = build_web_search_context_from_settings(
        settings,
        message="/search neutral topic",
        latest_user_message="/search neutral topic",
        decision_provider=decision_provider,
    )

    assert calls == []
    assert "[WEB_SEARCH_RESULTS]" in block


def test_build_web_search_context_does_not_call_decision_when_auto_disabled():
    calls = []
    settings = DummySettings(
        {
            "web_search_enabled": True,
            "web_search_auto_enabled": False,
            "web_search_provider": "tavily",
            "web_search_api_keys": {"tavily": "synthetic-key"},
        }
    )

    def decision_provider(latest_user_message, recent_context):
        calls.append((latest_user_message, recent_context))
        return WebSearchDecision(True, "should not run", "")

    block = build_web_search_context_from_settings(
        settings,
        message="latest neutral question",
        latest_user_message="latest neutral question",
        decision_provider=decision_provider,
    )

    assert calls == []
    assert block == ""


def test_web_search_runner_clamps_numeric_max_results():
    assert WebSearchToolRunner(search_tool=None, enabled=True, max_results=0).max_results == 1
    assert WebSearchToolRunner(search_tool=None, enabled=True, max_results=-3).max_results == 1


def test_web_search_runner_defaults_malformed_max_results():
    assert WebSearchToolRunner(search_tool=None, enabled=True, max_results=None).max_results == 5
    assert WebSearchToolRunner(search_tool=None, enabled=True, max_results="bad").max_results == 5
