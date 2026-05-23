from src.core.away_nudge import build_away_nudge_prompt


def test_build_away_nudge_prompt_for_stable_korean_screen():
    prompt = build_away_nudge_prompt(
        language="ko",
        idle_minutes=7,
        use_stable_screen=True,
        diff_percent=1.234,
    )

    assert "마스터가 현재 자리 비움 상태야" in prompt
    assert "최근 7분 동안" in prompt
    assert "차이율 1.23%" in prompt
    assert "자리 비운 마스터에게 남길 말을 짧게 해줘" in prompt


def test_build_away_nudge_prompt_for_changed_english_screen_without_diff():
    prompt = build_away_nudge_prompt(
        language="en",
        idle_minutes=12,
        use_stable_screen=False,
        diff_percent=None,
    )

    assert "Master has not talked to you for the last 12 minutes" in prompt
    assert "conservatively because comparison failed" in prompt
    assert "the screen appears to have changed" in prompt
    assert "would like Master to talk to you a little" in prompt
