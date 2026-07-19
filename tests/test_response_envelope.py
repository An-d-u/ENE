from dataclasses import FrozenInstanceError
import json

import pytest

from src.ai.response_envelope import (
    ANALYSIS_FIELDS,
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_ENVELOPE_V1_SCHEMA,
    TOP_LEVEL_FIELDS,
    build_response_requirements,
    decode_response_envelope,
    get_response_envelope_v1_schema,
    normalize_response_tuple,
)
from src.ai.response_parser import parse_llm_response
from tests.structured_response_fixtures import (
    all_enabled_requirements,
    make_requirements,
    make_valid_envelope,
    thought_and_tts_requirements,
    thought_enabled_requirements,
    valid_envelope_json,
)


class _GetSettings:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class _ConfigSettings:
    def __init__(self, values):
        self.config = values


class _RaisingGetSettings:
    def __init__(self, values):
        self.config = values

    def get(self, key, default=None):
        raise RuntimeError("합성 설정 저장소 오류")


def _assert_strict_objects(schema):
    if schema.get("type") == "object":
        properties = schema["properties"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(properties)
        for child in properties.values():
            _assert_strict_objects(child)
    if schema.get("type") == "array":
        _assert_strict_objects(schema["items"])


def _assert_forbidden_schema_constructs_are_absent(schema):
    assert "oneOf" not in schema
    assert "pattern" not in schema
    assert "minLength" not in schema
    schema_type = schema.get("type")
    assert schema_type != "null"
    if isinstance(schema_type, list):
        assert "null" not in schema_type
    for value in schema.values():
        if isinstance(value, dict):
            _assert_forbidden_schema_constructs_are_absent(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _assert_forbidden_schema_constructs_are_absent(item)


def test_response_schema_requires_every_object_property_recursively():
    assert RESPONSE_ENVELOPE_SCHEMA_NAME == "ene_response_envelope_v1"
    _assert_strict_objects(RESPONSE_ENVELOPE_V1_SCHEMA)


def test_response_schema_getter_returns_recursively_independent_runtime_copies():
    first = get_response_envelope_v1_schema()
    second = get_response_envelope_v1_schema()

    assert first == RESPONSE_ENVELOPE_V1_SCHEMA
    assert second == RESPONSE_ENVELOPE_V1_SCHEMA
    assert first is not second
    assert first["properties"] is not second["properties"]
    assert (
        first["properties"]["analysis"]["properties"]
        is not second["properties"]["analysis"]["properties"]
    )

    first["required"].pop()
    first["properties"]["analysis"]["properties"]["confidence"]["type"] = "number"

    assert tuple(second["required"]) == TOP_LEVEL_FIELDS
    assert (
        second["properties"]["analysis"]["properties"]["confidence"]["type"]
        == "string"
    )
    assert tuple(RESPONSE_ENVELOPE_V1_SCHEMA["required"]) == TOP_LEVEL_FIELDS
    assert (
        RESPONSE_ENVELOPE_V1_SCHEMA["properties"]["analysis"]["properties"]["confidence"]["type"]
        == "string"
    )


def test_response_schema_has_exact_canonical_top_level_fields():
    properties = RESPONSE_ENVELOPE_V1_SCHEMA["properties"]

    assert tuple(properties) == TOP_LEVEL_FIELDS
    assert tuple(RESPONSE_ENVELOPE_V1_SCHEMA["required"]) == TOP_LEVEL_FIELDS
    assert "schema_version" not in properties


def test_response_schema_has_exact_top_level_types():
    properties = RESPONSE_ENVELOPE_V1_SCHEMA["properties"]

    assert {name: schema["type"] for name, schema in properties.items()} == {
        "reply": "string",
        "emotion": "string",
        "tts_text": "string",
        "events": "array",
        "analysis": "object",
        "promises": "array",
        "thought": "string",
        "goal_update": "object",
        "proactive_conversations": "array",
        "gesture": "string",
    }


@pytest.mark.parametrize(
    ("field", "expected_fields"),
    [
        ("events", ("date", "title", "description")),
        ("promises", ("trigger_at", "title", "source", "source_excerpt")),
        (
            "proactive_conversations",
            (
                "trigger_at",
                "title",
                "generation_prompt",
                "source_excerpt",
                "reason",
                "cooldown_key",
            ),
        ),
    ],
)
def test_response_schema_array_items_have_exact_string_fields(field, expected_fields):
    item_schema = RESPONSE_ENVELOPE_V1_SCHEMA["properties"][field]["items"]

    assert tuple(item_schema["properties"]) == expected_fields
    assert all(schema["type"] == "string" for schema in item_schema["properties"].values())


def test_response_schema_analysis_has_exact_string_fields():
    properties = RESPONSE_ENVELOPE_V1_SCHEMA["properties"]["analysis"]["properties"]

    assert tuple(properties) == ANALYSIS_FIELDS
    assert all(schema["type"] == "string" for schema in properties.values())
    assert properties["confidence"]["type"] == "string"
    assert properties["flags"]["type"] == "string"


def test_response_schema_goal_update_has_exact_string_fields():
    properties = RESPONSE_ENVELOPE_V1_SCHEMA["properties"]["goal_update"]["properties"]

    assert tuple(properties) == (
        "action",
        "type",
        "id",
        "title",
        "reason",
        "completion_reason",
    )
    assert all(schema["type"] == "string" for schema in properties.values())


def test_response_schema_avoids_provider_incompatible_constructs():
    _assert_forbidden_schema_constructs_are_absent(RESPONSE_ENVELOPE_V1_SCHEMA)


def test_response_requirements_are_a_request_scoped_snapshot():
    cooldown_keys = ["quiet-checkin", "task-momentum"]
    settings = {
        "enable_ene_thoughts": True,
        "ui_language": "ko",
        "tts_language": "ja",
        "proactive_available_cooldown_keys": cooldown_keys,
    }
    emotions = ["normal", "smile"]

    requirements = build_response_requirements(settings, available_emotions=emotions)
    settings["enable_ene_thoughts"] = False
    settings["tts_language"] = "ko"
    emotions.append("surprise")
    cooldown_keys.clear()

    assert requirements.require_thought is True
    assert requirements.require_tts_text is True
    assert requirements.allowed_emotions == ("normal", "smile")
    assert requirements.allowed_proactive_cooldown_keys == (
        "quiet-checkin",
        "task-momentum",
    )


def test_response_requirements_map_all_disabled_feature_toggles():
    settings = {
        "ui_language": "en",
        "tts_language": "same_as_response",
        "enable_ene_thoughts": False,
        "enable_response_analysis": False,
        "enable_schedule_recognition": False,
        "enable_conversation_promises": False,
        "enable_ene_goals": False,
        "enable_proactive_conversation": False,
        "enable_synthetic_gestures": False,
    }

    requirements = build_response_requirements(settings)

    assert requirements.response_language == "en"
    assert requirements.tts_language == "en"
    assert requirements.require_tts_text is False
    assert requirements.require_thought is False
    assert requirements.enable_analysis is False
    assert requirements.enable_events is False
    assert requirements.enable_promises is False
    assert requirements.enable_goal_update is False
    assert requirements.enable_proactive_conversations is False
    assert requirements.enable_gesture is False


def test_response_requirements_map_all_enabled_feature_toggles_and_different_tts_language():
    settings = {
        "ui_language": "ko",
        "tts_language": "ja",
        "enable_ene_thoughts": True,
        "enable_response_analysis": True,
        "enable_schedule_recognition": True,
        "enable_conversation_promises": True,
        "enable_ene_goals": True,
        "enable_proactive_conversation": True,
        "enable_synthetic_gestures": True,
        "proactive_available_cooldown_keys": ["task-momentum", "quiet-checkin"],
    }

    requirements = build_response_requirements(settings)

    assert requirements.response_language == "ko"
    assert requirements.tts_language == "ja"
    assert requirements.require_tts_text is True
    assert requirements.require_thought is True
    assert requirements.enable_analysis is True
    assert requirements.enable_events is True
    assert requirements.enable_promises is True
    assert requirements.enable_goal_update is True
    assert requirements.enable_proactive_conversations is True
    assert requirements.enable_gesture is True
    assert requirements.allowed_proactive_cooldown_keys == (
        "quiet-checkin",
        "task-momentum",
    )


def test_response_requirements_disable_proactive_when_no_cooldown_key_is_usable():
    requirements = build_response_requirements(
        {
            "enable_proactive_conversation": True,
            "proactive_available_cooldown_keys": ["unknown-key"],
        }
    )

    assert requirements.allowed_proactive_cooldown_keys == ()
    assert requirements.enable_proactive_conversations is False


def test_response_requirements_are_frozen():
    requirements = build_response_requirements({})

    with pytest.raises(FrozenInstanceError):
        requirements.require_thought = False


def test_response_requirements_support_get_settings_source():
    requirements = build_response_requirements(
        _GetSettings(
            {
                "ui_language": "en",
                "tts_language": "same_as_response",
                "enable_ene_thoughts": False,
                "proactive_available_cooldown_keys": ["quiet-checkin"],
            }
        )
    )

    assert requirements.response_language == "en"
    assert requirements.tts_language == "en"
    assert requirements.require_thought is False
    assert requirements.require_tts_text is False
    assert requirements.enable_proactive_conversations is True
    assert requirements.allowed_proactive_cooldown_keys == ("quiet-checkin",)


def test_response_requirements_support_config_settings_source():
    requirements = build_response_requirements(
        _ConfigSettings(
            {
                "ui_language": "ja",
                "tts_language": "ko",
                "enable_response_analysis": False,
                "enable_synthetic_gestures": False,
                "proactive_available_cooldown_keys": ["task-momentum"],
            }
        )
    )

    assert requirements.response_language == "ja"
    assert requirements.tts_language == "ko"
    assert requirements.require_tts_text is True
    assert requirements.enable_analysis is False
    assert requirements.enable_gesture is False
    assert requirements.allowed_proactive_cooldown_keys == ("task-momentum",)


def test_response_requirements_fall_back_to_config_when_get_raises():
    requirements = build_response_requirements(
        _RaisingGetSettings(
            {
                "ui_language": "en",
                "tts_language": "ja",
                "enable_ene_goals": False,
                "enable_proactive_conversation": False,
                "proactive_available_cooldown_keys": ["quiet-checkin"],
            }
        )
    )

    assert requirements.response_language == "en"
    assert requirements.tts_language == "ja"
    assert requirements.require_tts_text is True
    assert requirements.enable_goal_update is False
    assert requirements.enable_proactive_conversations is False
    assert requirements.allowed_proactive_cooldown_keys == ("quiet-checkin",)


def test_synthetic_fixture_returns_independent_exact_envelopes():
    first = make_valid_envelope()
    second = make_valid_envelope()

    first["analysis"]["confidence"] = "high"

    assert tuple(first) == TOP_LEVEL_FIELDS
    assert tuple(second) == TOP_LEVEL_FIELDS
    assert second["analysis"]["confidence"] == ""


def test_valid_envelope_maps_to_existing_tuple_order():
    decoded = decode_response_envelope(
        json.dumps(
            make_valid_envelope(
                reply="중립적인 합성 답변",
                emotion="허용되지-않은-감정",
                thought="짧은 합성 내면 반응",
            ),
            ensure_ascii=False,
        ),
        requirements=thought_enabled_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[0] == "중립적인 합성 답변"
    assert decoded.payload[1] == "normal"
    assert decoded.payload[6] == "짧은 합성 내면 반응"
    assert len(decoded.payload) == 10
    assert decoded.present_fields == frozenset(TOP_LEVEL_FIELDS)
    assert decoded.has_valid_reply is True


def test_decoder_preserves_reply_and_drops_invalid_side_effect_items():
    envelope = make_valid_envelope(reply="보존할 합성 답변", thought="합성 내면 반응")
    envelope["events"] = [
        {"date": "", "title": "잘못된 항목", "description": "", "extra": "x"}
    ]
    envelope["promises"] = [
        {
            "trigger_at": "",
            "title": "잘못된 약속",
            "source": "user",
            "source_excerpt": "",
        }
    ]
    envelope["unknown_root"] = "ignored"

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=all_enabled_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[0] == "보존할 합성 답변"
    assert decoded.payload[3] == []
    assert decoded.payload[5] == []
    assert decoded.invalid_paths == (
        "events[0].<extra>",
        "events[0].date",
        "promises[0].trigger_at",
        "root.<extra>",
    )


def test_decoder_reports_only_enabled_missing_thought_and_translation_tts():
    envelope = make_valid_envelope(reply="합성 답변", thought="", tts_text="")
    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=thought_and_tts_requirements(),
    )

    assert decoded.missing_required_fields == ("thought", "tts_text")


@pytest.mark.parametrize(
    ("carrier", "root_error"),
    [
        ("not-json", "invalid_json"),
        (json.dumps(["합성 값"]), "root_not_object"),
        (json.dumps(make_valid_envelope(reply="   ")), "reply_missing_or_invalid"),
    ],
)
def test_decoder_rejects_non_object_root_and_blank_reply(carrier, root_error):
    decoded = decode_response_envelope(carrier, requirements=make_requirements())

    assert decoded.payload is None
    assert decoded.has_valid_reply is False
    assert decoded.root_error == root_error
    assert "합성 값" not in decoded.root_error


def test_decoder_normalizes_disabled_features_and_same_language_tts():
    envelope = make_valid_envelope(
        reply="재사용할 합성 답변",
        emotion="normal",
        tts_text="사용하지 않을 별도 음성 문장",
        events=[{"date": "2026-08-01", "title": "합성 일정", "description": ""}],
        analysis={"user_intent": "synthetic"},
        promises=[
            {
                "trigger_at": "2026-08-01T12:00:00+09:00",
                "title": "합성 약속",
                "source": "user",
                "source_excerpt": "",
            }
        ],
        thought="사용하지 않을 합성 내면 반응",
        goal_update={
            "action": "create",
            "type": "short_term",
            "id": "",
            "title": "합성 목표",
            "reason": "합성 이유",
            "completion_reason": "",
        },
        proactive_conversations=[
            {
                "trigger_at": "2026-08-01T12:10:00+09:00",
                "title": "합성 선제 대화",
                "generation_prompt": "중립적인 후속 질문을 생성한다.",
                "source_excerpt": "",
                "reason": "합성 이유",
                "cooldown_key": "synthetic",
            }
        ],
        gesture="nod",
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=make_requirements(),
    )

    assert decoded.payload == (
        "재사용할 합성 답변",
        "normal",
        "재사용할 합성 답변",
        [],
        {},
        [],
        "",
        {},
        [],
        "",
    )
    assert decoded.missing_required_fields == ()


def test_decoder_validates_goal_actions_and_limits_proactive_items_to_one():
    proactive_item = {
        "trigger_at": "2026-08-01T12:10:00+09:00",
        "title": "합성 선제 대화",
        "generation_prompt": "중립적인 후속 질문을 생성한다.",
        "source_excerpt": "합성 흐름",
        "reason": "합성 이유",
        "cooldown_key": "synthetic",
    }
    envelope = make_valid_envelope(
        reply="합성 답변",
        thought="합성 내면 반응",
        goal_update={
            "action": "update",
            "type": "short_term",
            "id": "",
            "title": "합성 목표",
            "reason": "",
            "completion_reason": "",
        },
        proactive_conversations=[proactive_item, dict(proactive_item, title="두 번째 합성 항목")],
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=all_enabled_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[7] == {}
    assert decoded.payload[8] == [proactive_item]
    assert "goal_update.id" in decoded.invalid_paths
    assert "proactive_conversations[1]" in decoded.invalid_paths


def test_decoder_normalizes_invalid_emotion_and_gesture():
    envelope = make_valid_envelope(
        reply="합성 답변",
        emotion="unknown",
        gesture="moonwalk",
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=make_requirements(
            enable_gesture=True,
            allowed_emotions=("normal", "smile"),
        ),
    )

    assert decoded.payload is not None
    assert decoded.payload[1] == "normal"
    assert decoded.payload[9] == ""
    assert decoded.invalid_paths == ("emotion", "gesture")


def test_legacy_tuple_uses_the_same_domain_normalizer():
    parsed = parse_llm_response(
        """[ene_goal_update]
action=create
type=short_term
id=
title=합성 목표
reason=
completion_reason=
[/ene_goal_update]
합성 답변 [event:|합성 일정|설명] [gesture:moonwalk]""",
        settings_source={
            "enable_ene_thoughts": False,
            "tts_language": "same_as_response",
        },
        available_emotions={"normal"},
    )

    assert parsed[0] == "합성 답변"
    assert parsed[2] == "합성 답변"
    assert parsed[3] == []
    assert parsed[7] == {}
    assert parsed[9] == ""


def test_decoder_update_goal_omits_blank_mutable_fields():
    envelope = make_valid_envelope(
        reply="합성 답변",
        thought="합성 내면 반응",
        goal_update={
            "action": "update",
            "type": "",
            "id": "goal-synthetic",
            "title": "",
            "reason": "조정된 합성 이유",
            "completion_reason": "",
        },
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=all_enabled_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[7] == {
        "action": "update",
        "id": "goal-synthetic",
        "reason": "조정된 합성 이유",
    }


def test_decoder_recovers_second_valid_proactive_after_invalid_first():
    invalid_item = {
        "trigger_at": "",
        "title": "잘못된 합성 항목",
        "generation_prompt": "중립적인 후속 질문을 생성한다.",
        "source_excerpt": "",
        "reason": "합성 이유",
        "cooldown_key": "synthetic",
    }
    valid_item = dict(
        invalid_item,
        trigger_at="2026-08-01T12:10:00+09:00",
        title="회수할 합성 항목",
    )
    envelope = make_valid_envelope(
        reply="합성 답변",
        thought="합성 내면 반응",
        proactive_conversations=[invalid_item, valid_item],
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=all_enabled_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[8] == [valid_item]
    assert "proactive_conversations[0].trigger_at" in decoded.invalid_paths
    assert "proactive_conversations[1]" not in decoded.invalid_paths


def test_decoder_diagnoses_disabled_field_structure_before_empty_normalization():
    envelope = make_valid_envelope(
        reply="합성 답변",
        tts_text=123,
        events=[{"date": "2026-08-01", "title": "합성 일정", "extra": "x"}],
        analysis=[],
        promises="invalid",
        thought=["invalid"],
        goal_update=[],
        proactive_conversations={"invalid": True},
        gesture=123,
    )

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=make_requirements(),
    )

    assert decoded.payload == (
        "합성 답변",
        "normal",
        "합성 답변",
        [],
        {},
        [],
        "",
        {},
        [],
        "",
    )
    assert {
        "analysis",
        "events[0].description",
        "events[0].<extra>",
        "gesture",
        "goal_update",
        "promises",
        "proactive_conversations",
        "thought",
        "tts_text",
    }.issubset(decoded.invalid_paths)


def test_decoder_diagnoses_root_shape_even_when_reply_is_invalid():
    decoded = decode_response_envelope(
        json.dumps({"reply": " ", "unknown_root": "ignored"}),
        requirements=make_requirements(),
    )

    assert decoded.payload is None
    assert decoded.present_fields == frozenset({"reply"})
    assert decoded.root_error == "reply_missing_or_invalid"
    assert decoded.invalid_paths == tuple(
        sorted(
            {
                "analysis",
                "emotion",
                "events",
                "gesture",
                "goal_update",
                "proactive_conversations",
                "promises",
                "reply",
                "thought",
                "tts_text",
                "root.<extra>",
            }
        )
    )


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_decoder_rejects_nonstandard_json_constants(constant):
    carrier = f'{{"reply":"합성 답변","emotion":{constant}}}'

    decoded = decode_response_envelope(carrier, requirements=make_requirements())

    assert decoded.payload is None
    assert decoded.present_fields == frozenset()
    assert decoded.invalid_paths == ()
    assert decoded.root_error == "invalid_json"
    assert constant not in decoded.root_error


def test_decoder_salvages_valid_analysis_values_from_malformed_object():
    analysis = make_valid_envelope()["analysis"]
    analysis["user_emotion"] = 123
    analysis["user_intent"] = " synthetic_valid "
    analysis["flags"] = "   "
    analysis.pop("confidence")
    analysis["unknown"] = "ignored"

    decoded = decode_response_envelope(
        json.dumps(make_valid_envelope(analysis=analysis), ensure_ascii=False),
        requirements=make_requirements(enable_analysis=True),
    )

    assert decoded.payload is not None
    assert decoded.payload[4] == {"user_intent": "synthetic_valid"}
    assert decoded.invalid_paths == (
        "analysis.<extra>",
        "analysis.confidence",
        "analysis.user_emotion",
    )


@pytest.mark.parametrize("error_kind", ("wrong_type", "missing_key", "extra_key"))
@pytest.mark.parametrize(
    ("field_name", "tuple_index", "enable_flag", "wrong_key", "optional_key"),
    [
        ("events", 3, "enable_events", "date", "description"),
        ("promises", 5, "enable_promises", "trigger_at", "source_excerpt"),
        (
            "proactive_conversations",
            8,
            "enable_proactive_conversations",
            "generation_prompt",
            "source_excerpt",
        ),
    ],
)
def test_decoder_drops_only_malformed_structured_side_effect_item(
    error_kind,
    field_name,
    tuple_index,
    enable_flag,
    wrong_key,
    optional_key,
):
    valid_items = {
        "events": {
            "date": "2026-08-01",
            "title": "합성 일정",
            "description": "합성 설명",
        },
        "promises": {
            "trigger_at": "2026-08-01T12:00:00+09:00",
            "title": "합성 약속",
            "source": "user",
            "source_excerpt": "합성 근거",
        },
        "proactive_conversations": {
            "trigger_at": "2026-08-01T12:10:00+09:00",
            "title": "합성 선제 대화",
            "generation_prompt": "중립적인 후속 질문을 생성한다.",
            "source_excerpt": "합성 흐름",
            "reason": "합성 이유",
            "cooldown_key": "synthetic",
        },
    }
    valid_item = valid_items[field_name]
    invalid_item = dict(valid_item)
    if error_kind == "wrong_type":
        invalid_item[wrong_key] = 123
        invalid_path = f"{field_name}[0].{wrong_key}"
    elif error_kind == "missing_key":
        invalid_item.pop(optional_key)
        invalid_path = f"{field_name}[0].{optional_key}"
    else:
        invalid_item["extra"] = "ignored"
        invalid_path = f"{field_name}[0].<extra>"

    decoded = decode_response_envelope(
        json.dumps(
            make_valid_envelope(**{field_name: [invalid_item, valid_item]}),
            ensure_ascii=False,
        ),
        requirements=make_requirements(**{enable_flag: True}),
    )

    assert decoded.payload is not None
    assert decoded.payload[tuple_index] == [valid_item]
    assert invalid_path in decoded.invalid_paths


def _make_goal_update(**overrides):
    payload = {
        "action": "none",
        "type": "",
        "id": "",
        "title": "",
        "reason": "",
        "completion_reason": "",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("goal_update", "expected"),
    [
        (_make_goal_update(), {}),
        (
            _make_goal_update(
                action="create",
                type="short_term",
                title="합성 목표",
                reason="합성 이유",
            ),
            _make_goal_update(
                action="create",
                type="short_term",
                title="합성 목표",
                reason="합성 이유",
            ),
        ),
        (
            _make_goal_update(
                action="update",
                id="goal-synthetic",
                title="수정된 합성 목표",
            ),
            {
                "action": "update",
                "id": "goal-synthetic",
                "title": "수정된 합성 목표",
            },
        ),
        (
            _make_goal_update(
                action="complete",
                id="goal-synthetic",
                completion_reason="합성 완료 이유",
            ),
            _make_goal_update(
                action="complete",
                id="goal-synthetic",
                completion_reason="합성 완료 이유",
            ),
        ),
        (
            _make_goal_update(
                action="cancel",
                id="goal-synthetic",
                completion_reason="합성 취소 이유",
            ),
            _make_goal_update(
                action="cancel",
                id="goal-synthetic",
                completion_reason="합성 취소 이유",
            ),
        ),
    ],
)
def test_decoder_accepts_valid_goal_actions(goal_update, expected):
    decoded = decode_response_envelope(
        json.dumps(make_valid_envelope(goal_update=goal_update), ensure_ascii=False),
        requirements=make_requirements(enable_goal_update=True),
    )

    assert decoded.payload is not None
    assert decoded.payload[7] == expected


@pytest.mark.parametrize(
    ("goal_update", "expected_invalid_paths"),
    [
        (
            _make_goal_update(
                action="create",
                title="합성 목표",
                reason="합성 이유",
            ),
            {"goal_update.type"},
        ),
        (
            _make_goal_update(
                action="create",
                type="short_term",
                reason="합성 이유",
            ),
            {"goal_update.title"},
        ),
        (
            _make_goal_update(
                action="create",
                type="short_term",
                title="합성 목표",
            ),
            {"goal_update.reason"},
        ),
        (
            _make_goal_update(action="update", title="수정된 합성 목표"),
            {"goal_update.id"},
        ),
        (
            _make_goal_update(action="update", id="goal-synthetic"),
            {"goal_update.title", "goal_update.reason"},
        ),
        (
            _make_goal_update(action="complete", completion_reason="합성 완료 이유"),
            {"goal_update.id"},
        ),
        (
            _make_goal_update(action="cancel", completion_reason="합성 취소 이유"),
            {"goal_update.id"},
        ),
        (
            _make_goal_update(
                action="create",
                type="unsupported",
                title="합성 목표",
                reason="합성 이유",
            ),
            {"goal_update.type"},
        ),
        (_make_goal_update(action="unsupported"), {"goal_update.action"}),
    ],
)
def test_decoder_rejects_invalid_goal_actions(goal_update, expected_invalid_paths):
    decoded = decode_response_envelope(
        json.dumps(make_valid_envelope(goal_update=goal_update), ensure_ascii=False),
        requirements=make_requirements(enable_goal_update=True),
    )

    assert decoded.payload is not None
    assert decoded.payload[7] == {}
    assert expected_invalid_paths.issubset(decoded.invalid_paths)


def test_decoder_rejects_proactive_item_with_unavailable_cooldown_key():
    proactive_item = {
        "trigger_at": "2026-08-01T12:10:00+09:00",
        "title": "합성 선제 대화",
        "generation_prompt": "중립적인 후속 질문을 생성한다.",
        "source_excerpt": "합성 흐름",
        "reason": "합성 이유",
        "cooldown_key": "unavailable",
    }

    decoded = decode_response_envelope(
        json.dumps(
            make_valid_envelope(proactive_conversations=[proactive_item]),
            ensure_ascii=False,
        ),
        requirements=make_requirements(enable_proactive_conversations=True),
    )

    assert decoded.payload is not None
    assert decoded.payload[8] == []
    assert decoded.invalid_paths == ("proactive_conversations[0].cooldown_key",)


def test_structured_exact_keys_and_legacy_semantics_treat_optional_item_keys_differently():
    item_without_optional_key = {
        "date": "2026-08-01",
        "title": "합성 일정",
    }
    requirements = make_requirements(enable_events=True)

    structured = decode_response_envelope(
        json.dumps(
            make_valid_envelope(events=[item_without_optional_key]),
            ensure_ascii=False,
        ),
        requirements=requirements,
    )
    legacy = normalize_response_tuple(
        (
            "합성 답변",
            "normal",
            "",
            [item_without_optional_key],
            {},
            [],
            "",
            {},
            [],
            "",
        ),
        requirements=requirements,
    )

    assert structured.payload is not None
    assert structured.payload[3] == []
    assert structured.invalid_paths == ("events[0].description",)
    assert legacy[3] == [
        {
            "date": "2026-08-01",
            "title": "합성 일정",
            "description": "",
        }
    ]


def test_structured_and_legacy_none_goal_keep_compatibility_forms():
    structured = decode_response_envelope(
        json.dumps(make_valid_envelope(), ensure_ascii=False),
        requirements=make_requirements(enable_goal_update=True),
    )
    legacy = parse_llm_response(
        """[ene_goal_update]
action=none
[/ene_goal_update]
합성 답변""",
        settings_source={
            "enable_ene_goals": True,
            "enable_ene_thoughts": False,
            "tts_language": "same_as_response",
        },
        available_emotions={"normal"},
    )

    assert structured.payload is not None
    assert structured.payload[7] == {}
    assert legacy[7] == {"action": "none"}


def test_decoder_redacts_unknown_key_names_from_all_result_diagnostics():
    root_key = "synthetic-sensitive-root-key"
    item_key = "synthetic-sensitive-item-key"
    analysis_key = "synthetic-sensitive-analysis-key"
    event = {
        "date": "2026-08-01",
        "title": "합성 일정",
        "description": "합성 설명",
        item_key: "ignored",
    }
    analysis = make_valid_envelope()["analysis"]
    analysis[analysis_key] = "ignored"
    envelope = make_valid_envelope(events=[event], analysis=analysis)
    envelope[root_key] = "ignored"

    decoded = decode_response_envelope(
        json.dumps(envelope, ensure_ascii=False),
        requirements=all_enabled_requirements(),
    )

    rendered = repr(decoded)
    for unknown_key in (root_key, item_key, analysis_key):
        assert all(unknown_key not in path for path in decoded.invalid_paths)
        assert unknown_key not in (decoded.root_error or "")
        assert unknown_key not in rendered
    assert {
        "root.<extra>",
        "events[0].<extra>",
        "analysis.<extra>",
    }.issubset(decoded.invalid_paths)


def test_legacy_parser_recovers_second_valid_proactive_after_invalid_cooldown():
    parsed = parse_llm_response(
        """합성 답변
[proactive_conversation]
trigger_at=2026-08-01T12:00:00+09:00
title=폐기할 합성 후보
generation_prompt=첫 번째 합성 질문을 만든다.
source_excerpt=합성 근거 하나
reason=합성 이유 하나
cooldown_key=unavailable
[/proactive_conversation]
[proactive_conversation]
trigger_at=2026-08-01T12:10:00+09:00
title=회수할 합성 후보
generation_prompt=두 번째 합성 질문을 만든다.
source_excerpt=합성 근거 둘
reason=합성 이유 둘
cooldown_key=short-followup
[/proactive_conversation]""",
        settings_source={
            "enable_proactive_conversation": True,
            "proactive_available_cooldown_keys": ["short-followup"],
        },
        available_emotions={"normal"},
    )

    assert parsed[8] == [
        {
            "trigger_at": "2026-08-01T12:10:00+09:00",
            "title": "회수할 합성 후보",
            "generation_prompt": "두 번째 합성 질문을 만든다.",
            "source_excerpt": "합성 근거 둘",
            "reason": "합성 이유 둘",
            "cooldown_key": "short-followup",
        }
    ]


def test_decoder_maps_recursion_error_to_content_free_invalid_json(monkeypatch):
    carrier = "synthetic-deep-carrier"
    exception_detail = "synthetic-recursion-detail"

    def raise_recursion_error(*_args, **_kwargs):
        raise RecursionError(exception_detail)

    monkeypatch.setattr("src.ai.response_envelope.json.loads", raise_recursion_error)

    decoded = decode_response_envelope(carrier, requirements=make_requirements())

    assert decoded.payload is None
    assert decoded.present_fields == frozenset()
    assert decoded.missing_required_fields == ()
    assert decoded.invalid_paths == ()
    assert decoded.root_error == "invalid_json"
    assert carrier not in repr(decoded)
    assert exception_detail not in repr(decoded)


def test_repair_schema_canonicalizes_requested_fields_and_rejects_unknowns():
    import src.ai.response_envelope as response_envelope

    schema = response_envelope.get_response_repair_schema(
        ("tts_text", "thought", "tts_text")
    )

    assert response_envelope.RESPONSE_REPAIR_SCHEMA_NAME == "ene_response_repair_v1"
    assert schema["required"] == ["thought", "tts_text"]
    assert list(schema["properties"]) == ["thought", "tts_text"]
    assert schema["additionalProperties"] is False
    for invalid_fields in ((), ("unknown",), ("",), "thought", (None,)):
        with pytest.raises(ValueError, match="repair fields"):
            response_envelope.get_response_repair_schema(invalid_fields)


def test_missing_repair_fields_follow_feature_and_language_requirements():
    import src.ai.response_envelope as response_envelope

    decoded = decode_response_envelope(
        valid_envelope_json(thought="", tts_text=""),
        requirements=thought_and_tts_requirements(),
    )

    assert decoded.payload is not None
    assert response_envelope.get_missing_response_repair_fields(
        decoded.payload,
        requirements=thought_and_tts_requirements(),
    ) == ("thought", "tts_text")
    assert response_envelope.get_missing_response_repair_fields(
        decoded.payload,
        requirements=make_requirements(),
    ) == ()


def test_structured_repair_decoder_salvages_requested_nonempty_strings_only():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = json.dumps(
        {
            "thought": "  회수할 합성 생각  ",
            "tts_text": 123,
            "reply": "무시할 대체 답변",
            "events": [{"title": "무시할 합성 일정"}],
        },
        ensure_ascii=False,
    )

    decoded = response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.JSON_SCHEMA,
        fields=("thought", "tts_text"),
    )

    assert decoded == {"thought": "회수할 합성 생각"}


@pytest.mark.parametrize(
    "carrier",
    ("synthetic-not-json", "[]", "null", '{"thought":"  "}', None),
)
def test_structured_repair_decoder_safely_rejects_malformed_carriers(carrier):
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.JSON_OBJECT,
        fields=("thought",),
    ) == {}


def test_legacy_repair_decoder_uses_only_closed_requested_control_blocks():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = """[thought]  회수할 합성 생각  [/thought]
[tts]Recovered synthetic speech[/tts]
[event:2099-01-01|무시할 합성 일정|]
[ene_goal_update]
action=create
[/ene_goal_update]"""

    decoded = response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought", "tts_text"),
    )
    thought_only = response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought",),
    )

    assert decoded == {
        "thought": "회수할 합성 생각",
        "tts_text": "Recovered synthetic speech",
    }
    assert thought_only == {"thought": "회수할 합성 생각"}


def test_legacy_repair_decoder_ignores_unclosed_requested_blocks():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = """[thought]닫히지 않은 합성 생각
[tts]닫힌 합성 음성[/tts]"""

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought", "tts_text"),
    ) == {}


def test_repair_decoder_rejects_unknown_mode_and_field_contracts():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    with pytest.raises(ValueError, match="response mode"):
        response_envelope.decode_response_repair(
            "{}",
            mode="synthetic-mode",
            fields=("thought",),
        )
    with pytest.raises(ValueError, match="repair fields"):
        response_envelope.decode_response_repair(
            "{}",
            mode=ResponseMode.JSON_SCHEMA,
            fields=("reply",),
        )


@pytest.mark.parametrize(
    "carrier",
    [
        "thought: 라벨로 위장한 합성 생각\n나머지 합성 텍스트",
        "[thought]바깥 합성 생각 [tts]중첩 음성[/tts][/thought]",
        "[thought]교차 합성 생각[/tts]",
        "<think>[thought]숨겨진 합성 생각[/thought]</think>",
    ],
    ids=("plain-label", "nested", "cross-family", "think-block"),
)
def test_legacy_repair_decoder_rejects_non_block_and_malformed_thought(carrier):
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought", "tts_text"),
    ) == {}


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ("thought", "subconscious"),
        ("ene_thought", "inner_thought"),
        ("생각", "속마음"),
        ("에네생각", "에네 생각"),
    ],
    ids=("english", "ene-english", "korean", "ene-korean"),
)
def test_legacy_repair_decoder_rejects_mismatched_thought_alias_pairs(
    opening,
    closing,
):
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    assert response_envelope.decode_response_repair(
        f"[{opening}]채택하면 안 되는 합성 생각[/{closing}]",
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought",),
    ) == {}


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ("subconscious", "SUBCONSCIOUS"),
        (" thought ", " THOUGHT "),
        ("ene_thought", "ENE_THOUGHT"),
        ("inner_thought", "INNER_THOUGHT"),
        ("생각", "생각"),
        ("속마음", "속마음"),
        ("에네생각", "에네생각"),
        ("에네   생각", "에네 생각"),
    ],
)
def test_legacy_repair_decoder_keeps_exact_thought_alias_compatibility(
    opening,
    closing,
):
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    assert response_envelope.decode_response_repair(
        f"[{opening}]호환할 합성 생각[/{closing}]",
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought",),
    ) == {"thought": "호환할 합성 생각"}


def test_legacy_repair_decoder_discards_unclosed_think_tail():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = """<think data-synthetic="1">
[thought]숨겨진 합성 생각[/thought]
[tts]Hidden synthetic speech[/tts]"""

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought", "tts_text"),
    ) == {}


def test_legacy_repair_decoder_accepts_valid_block_after_closed_think():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = """<think>[thought]숨겨진 합성 생각[/thought]</think>
[thought]채택할 합성 생각[/thought]"""

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought",),
    ) == {"thought": "채택할 합성 생각"}


def test_legacy_repair_decoder_uses_earliest_valid_exact_thought_block():
    import src.ai.response_envelope as response_envelope
    from src.ai.response_protocol import ResponseMode

    carrier = """[thought]무시할 교차 합성 생각[/subconscious]
[ene_thought]첫 번째 유효 합성 생각[/ene_thought]
[thought]두 번째 유효 합성 생각[/thought]"""

    assert response_envelope.decode_response_repair(
        carrier,
        mode=ResponseMode.LEGACY_TAGS,
        fields=("thought",),
    ) == {"thought": "첫 번째 유효 합성 생각"}


def test_native_envelope_sanitizes_legacy_wrapped_accessory_text():
    decoded = decode_response_envelope(
        valid_envelope_json(
            reply="[normal] Visible synthetic reply",
            thought="[subconscious] Public synthetic reaction [/subconscious]",
            tts_text="[tts]Synthetic translated speech[/tts]",
        ),
        requirements=thought_and_tts_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[0] == "Visible synthetic reply"
    assert decoded.payload[2] == "Synthetic translated speech"
    assert decoded.payload[6] == "Public synthetic reaction"
    assert decoded.missing_required_fields == ()


def test_native_envelope_rejects_reply_that_is_empty_after_visible_cleanup():
    decoded = decode_response_envelope(
        valid_envelope_json(
            reply="<think>hidden synthetic reasoning</think>"
        ),
        requirements=make_requirements(),
    )

    assert decoded.payload is None
    assert decoded.root_error == "reply_missing_or_invalid"
    assert "reply" in decoded.invalid_paths


def test_native_same_language_tts_reuses_the_sanitized_visible_reply():
    decoded = decode_response_envelope(
        valid_envelope_json(
            reply="[normal] Visible synthetic reply",
            tts_text="[tts]Unused synthetic speech[/tts]",
        ),
        requirements=make_requirements(),
    )

    assert decoded.payload is not None
    assert decoded.payload[0] == "Visible synthetic reply"
    assert decoded.payload[2] == "Visible synthetic reply"


def test_native_tts_preserves_legitimate_bracketed_plain_content():
    spoken_text = "Press [Enter] to continue the synthetic flow."
    decoded = decode_response_envelope(
        valid_envelope_json(tts_text=spoken_text),
        requirements=make_requirements(
            tts_language="en",
            require_tts_text=True,
        ),
    )

    assert decoded.payload is not None
    assert decoded.payload[2] == spoken_text
