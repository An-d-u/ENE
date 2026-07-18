from src.ai.response_parser import parse_llm_response
from tests.structured_response_fixtures import make_requirements


class _SettingsMustNotBeRead:
    def get(self, _key, _default=None):
        raise AssertionError("요구사항 스냅샷 전달 후 설정을 다시 읽으면 안 됩니다.")

    @property
    def config(self):
        raise AssertionError("요구사항 스냅샷 전달 후 설정을 다시 읽으면 안 됩니다.")


def test_parse_response_extracts_code_generated_event_tag():
    parsed = parse_llm_response(
        "알겠어요. [event:2026-03-15|프로젝트 회의|자료 점검] [smile]",
        available_emotions={"smile"},
    )

    clean_text, emotion, _tts_text, events, _analysis, promises, *_rest = parsed
    assert clean_text == "알겠어요."
    assert emotion == "smile"
    assert events == [
        {
            "date": "2026-03-15",
            "title": "프로젝트 회의",
            "description": "자료 점검",
        }
    ]
    assert promises == []


def test_parse_response_strips_disabled_schedule_and_promise_tags_without_metadata():
    parsed = parse_llm_response(
        "알겠어요. [event:2026-03-15|프로젝트 회의|] "
        "[약속:2026-03-15T20:00:00+09:00|다시 시작|user|이따 다시 할게] [smile]",
        settings_source={
            "enable_schedule_recognition": False,
            "enable_conversation_promises": False,
        },
        available_emotions={"smile"},
    )

    clean_text, emotion, _tts_text, events, _analysis, promises, *_rest = parsed
    assert clean_text == "알겠어요."
    assert emotion == "smile"
    assert events == []
    assert promises == []


def test_parse_response_uses_only_supplied_requirements_snapshot():
    requirements = make_requirements(
        response_language="ko",
        tts_language="ja",
        require_tts_text=True,
        enable_events=True,
        enable_promises=True,
        allowed_emotions=("normal", "joy"),
    )

    parsed = parse_llm_response(
        """합성 표시 답변 [event:2026-08-01|합성 일정|중립 설명]
[약속:2026-08-01T12:00:00+09:00|합성 약속|user|중립 근거] [joy]
これは合成音声です。""",
        settings_source=_SettingsMustNotBeRead(),
        available_emotions={"normal"},
        requirements=requirements,
    )

    assert parsed[0] == "합성 표시 답변"
    assert parsed[1] == "joy"
    assert parsed[2] == "これは合成音声です。"
    assert parsed[3] == [
        {
            "date": "2026-08-01",
            "title": "합성 일정",
            "description": "중립 설명",
        }
    ]
    assert parsed[5] == [
        {
            "trigger_at": "2026-08-01T12:00:00+09:00",
            "title": "합성 약속",
            "source": "user",
            "source_excerpt": "중립 근거",
        }
    ]
