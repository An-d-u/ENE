import requests

from src.ai.search_tool import SearchQuery, SearchTool, TavilySearchProvider


class DummyResponse:
    def __init__(self, *, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._json_data


def test_tavily_search_provider_normalizes_results(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(
            json_data={
                "query": "release notes",
                "results": [
                    {
                        "title": "Release Notes",
                        "url": "https://example.com/release",
                        "content": "A short neutral summary.",
                        "published_date": "2026-06-20",
                    }
                ],
            }
        )

    monkeypatch.setattr("src.ai.search_tool.requests.post", fake_post)

    provider = TavilySearchProvider(api_key="synthetic-key", timeout_sec=7)
    response = provider.search(SearchQuery(query="release notes", max_results=3))

    assert captured["url"] == "https://api.tavily.com/search"
    expected_authorization = "Bearer " + "synthetic-key"
    assert captured["headers"]["Authorization"] == expected_authorization
    assert captured["json"]["query"] == "release notes"
    assert captured["json"]["max_results"] == 3
    assert captured["timeout"] == 7
    assert response.provider == "tavily"
    assert response.query == "release notes"
    assert response.results[0].title == "Release Notes"
    assert response.results[0].url == "https://example.com/release"
    assert response.results[0].snippet == "A short neutral summary."
    assert response.results[0].published_at == "2026-06-20"


def test_tavily_search_provider_returns_empty_without_api_key():
    provider = TavilySearchProvider(api_key="")
    response = provider.search(SearchQuery(query="neutral query"))

    assert response.provider == "tavily"
    assert response.results == []


def test_tavily_search_provider_defaults_invalid_timeout():
    provider = TavilySearchProvider(api_key="synthetic", timeout_sec="bad")

    assert provider.timeout_sec == 12


def test_tavily_search_provider_clamps_timeout():
    provider = TavilySearchProvider(api_key="synthetic", timeout_sec=999)

    assert provider.timeout_sec == 60


def test_tavily_search_provider_defaults_invalid_max_results(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return DummyResponse(json_data={"query": "neutral", "results": []})

    monkeypatch.setattr("src.ai.search_tool.requests.post", fake_post)

    provider = TavilySearchProvider(api_key="synthetic")
    provider.search(SearchQuery(query="neutral", max_results="bad"))

    assert captured["json"]["max_results"] == 5


def test_tavily_search_provider_clamps_max_results(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return DummyResponse(json_data={"query": "neutral", "results": []})

    monkeypatch.setattr("src.ai.search_tool.requests.post", fake_post)

    provider = TavilySearchProvider(api_key="synthetic")
    provider.search(SearchQuery(query="neutral", max_results=999))

    assert captured["json"]["max_results"] == 10


def test_search_tool_swallow_errors_and_returns_empty(monkeypatch):
    class RaisingProvider:
        provider_name = "raising"

        def search(self, query):
            raise requests.Timeout("timed out")

    tool = SearchTool(RaisingProvider())
    response = tool.search(SearchQuery(query="neutral query"))

    assert response.provider == "raising"
    assert response.query == "neutral query"
    assert response.results == []


def test_search_tool_logs_provider_and_error_type_without_raw_error(capsys):
    class RaisingProvider:
        provider_name = "raising"

        def search(self, query):
            raise requests.Timeout("sensitive-token")

    tool = SearchTool(RaisingProvider())
    tool.search(SearchQuery(query="neutral query"))

    captured = capsys.readouterr()
    assert "provider=raising" in captured.out
    assert "error_type=Timeout" in captured.out
    assert "sensitive-token" not in captured.out
