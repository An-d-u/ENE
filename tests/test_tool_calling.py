from src.ai.search_tool import SearchResponse, SearchResult
from src.ai.tool_calling import build_search_context_block, parse_manual_search_command


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
