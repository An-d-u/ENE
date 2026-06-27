from src.ai.search_tool import SearchResponse, SearchResult
from src.ai.tool_calling import (
    WebSearchDecision,
    WebSearchToolRunner,
    build_search_context_block,
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
