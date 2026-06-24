from src.ai.response_parser import parse_llm_response


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
