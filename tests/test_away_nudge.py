from src.core.away_nudge import build_away_nudge_prompt


def test_build_away_nudge_prompt_for_no_recent_korean_input():
    prompt = build_away_nudge_prompt(
        language="ko",
        idle_minutes=7,
        input_grace_minutes=3,
        user_input_detected=False,
    )

    assert "마스터가 현재 자리 비움 상태야" in prompt
    assert "최근 7분 동안" in prompt
    assert "최근 3분 동안 마우스/키보드 입력도 없었어" in prompt
    assert "차이율" not in prompt
    assert "자리 비운 마스터에게 남길 말을 짧게 해줘" in prompt


def test_build_away_nudge_prompt_for_recent_english_input():
    prompt = build_away_nudge_prompt(
        language="en",
        idle_minutes=12,
        input_grace_minutes=5,
        user_input_detected=True,
    )

    assert "Master has not talked to you for the last 12 minutes" in prompt
    assert "keyboard or mouse input happened within the last 5 minutes" in prompt
    assert "would like Master to talk to you a little" in prompt


def test_build_away_nudge_prompt_uses_custom_user_name():
    prompt = build_away_nudge_prompt(
        language="en",
        idle_minutes=12,
        user_input_detected=True,
        user_name="Captain",
    )

    assert "Captain has not talked to you for the last 12 minutes" in prompt
    assert "would like Captain to talk to you a little" in prompt
    assert "Master" not in prompt


def test_build_away_nudge_prompt_uses_korean_particle_for_custom_user_name():
    prompt = build_away_nudge_prompt(
        language="ko",
        idle_minutes=7,
        user_input_detected=True,
        user_name="선장",
    )

    assert "선장이 최근 7분 동안" in prompt
    assert "선장가" not in prompt
