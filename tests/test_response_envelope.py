from dataclasses import FrozenInstanceError

import pytest

from src.ai.response_envelope import (
    ANALYSIS_FIELDS,
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_ENVELOPE_V1_SCHEMA,
    TOP_LEVEL_FIELDS,
    build_response_requirements,
    get_response_envelope_v1_schema,
)
from tests.structured_response_fixtures import make_valid_envelope


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
