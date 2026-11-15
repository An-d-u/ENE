import pytest

from src.core.away_nudge import away_greeting


@pytest.mark.parametrize("language", ["ko", "ja", "en"])
def test_away_greeting_is_ready_to_display(language):
    text = away_greeting(language)
    assert isinstance(text, str) and text.strip()
    assert len(text) <= 100
