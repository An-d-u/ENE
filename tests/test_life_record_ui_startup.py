from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.core.local_time import LocalTimeContext
from src.core.overlay_window import OverlayWindow


@pytest.mark.parametrize("language", ["ko", "en", "ja"])
def test_overlay_ui_payload_has_locale_language_view_timezone_and_local_today(language):
    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=lambda: datetime(2099, 4, 12, 9, 30, tzinfo=timezone.utc),
    )
    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = SimpleNamespace(config={"ui_language": language})
    overlay.life_time_context = context
    overlay.life_view_timezone = "Asia/Seoul"

    payload = OverlayWindow._resolve_ui_strings_payload(overlay)

    assert payload["locale"] == language
    assert payload["resolvedLanguage"] == language
    assert payload["viewTimezone"] == "Asia/Seoul"
    assert payload["todayIso"] == "2099-04-12"
