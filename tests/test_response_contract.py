import pytest

from src.ai.goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from src.ai.mood_engine import (
    CERTAINTIES,
    CLARITIES,
    CONTROLLABILITIES,
    EVENT_KINDS,
    RELATION_CATEGORIES,
    REPAIR_SIGNALS,
    TARGET_SCOPES,
)
from src.ai.response_contract import (
    build_legacy_response_contract_appendix,
    build_response_contract_appendix,
    build_structured_response_contract_appendix,
    is_proactive_conversation_enabled,
)


@pytest.mark.parametrize(
    ("language", "semantic_heading", "markers", "forbidden_only_phrase"),
    [
        (
            "ko",
            "### 기분 사건 분류 의미 규칙",
            ("관계 손상", "응급", "사건을 인정", "책임을 인정", "책임 회피가 아닌 맥락 설명", "실제 교정", "실제 이행", "안전 우선순위"),
            "질감으로만 안전하게 반영",
        ),
        (
            "en",
            "### Mood event classification semantic rules",
            ("relationship damage", "urgent", "recognizes the event", "accepts responsibility", "context without evading responsibility", "actual correction", "actual follow-through", "safety priority"),
            "only through tone",
        ),
        (
            "ja",
            "### 気分イベント分類の意味ルール",
            ("関係悪化", "緊急", "出来事を認め", "責任を認め", "責任逃れではない文脈説明", "実際の訂正", "実際の履行", "安全優先順位"),
            "だけで安全に反映",
        ),
    ],
)
def test_structured_mood_semantics_are_complete_and_localized_without_drift(
    language, semantic_heading, markers, forbidden_only_phrase
):
    from src.ai.analysis_prompt import build_analysis_system_appendix

    settings = {
        "ui_language": language,
        "enable_mood_system": True,
        "enable_response_analysis": True,
        "enable_schedule_recognition": False,
        "enable_conversation_promises": False,
    }
    analysis_appendix = build_analysis_system_appendix(
        settings, response_style="structured_fields"
    )
    response_appendix = build_structured_response_contract_appendix(settings)

    for marker in markers:
        assert marker in analysis_appendix
        assert marker in response_appendix
    assert forbidden_only_phrase not in analysis_appendix
    assert forbidden_only_phrase not in response_appendix
    assert analysis_appendix.count(semantic_heading) == 1
    assert response_appendix.count(semantic_heading) == 1
    for value in (
        "clarity=ambiguous",
        "target_scope=external",
        "repair_signal",
        "kind=repair",
        "risk_class=urgent",
        "proactive",
        "cooperative",
        "brief",
        "limited",
        "distance",
        "decline",
        "boundary",
    ):
        assert value in analysis_appendix
        assert value in response_appendix


@pytest.mark.parametrize(
    ("language", "semantic_heading"),
    [
        ("ko", "### 기분 사건 분류 의미 규칙"),
        ("en", "### Mood event classification semantic rules"),
        ("ja", "### 気分イベント分類の意味ルール"),
    ],
)
def test_legacy_mood_contract_uses_shared_semantic_block_once(
    language, semantic_heading
):
    appendix = build_legacy_response_contract_appendix(
        {
            "ui_language": language,
            "enable_mood_system": True,
            "enable_response_analysis": True,
        }
    )

    assert appendix.count(semantic_heading) == 1


@pytest.mark.parametrize("language", ["ko", "en", "ja"])
@pytest.mark.parametrize("structured", [False, True])
def test_active_mood_contract_lists_exact_fields_and_all_domain_enums(language, structured):
    builder = (
        build_response_contract_appendix
        if not structured
        else build_structured_response_contract_appendix
    )
    appendix = builder(
        {
            "ui_language": language,
            "enable_mood_system": True,
            "enable_response_analysis": True,
        }
    )
    for field in (
        "kind", "target_scope", "relation_category", "intensity", "clarity",
        "certainty", "controllability", "repair_signal", "risk_class",
        "proposed_stance",
    ):
        assert field in appendix
    for value in (
        *EVENT_KINDS, *TARGET_SCOPES, *RELATION_CATEGORIES, *CLARITIES,
        *CERTAINTIES, *CONTROLLABILITIES, *REPAIR_SIGNALS,
        "0", "1", "2", "3", "none", "concern", "urgent", "proactive",
        "cooperative", "brief", "limited", "distance", "decline", "boundary",
    ):
        assert value in appendix


@pytest.mark.parametrize("language", ["ko", "en", "ja"])
def test_inactive_structured_mood_contract_requires_null_without_enum_details(language):
    appendix = build_structured_response_contract_appendix(
        {
            "ui_language": language,
            "enable_mood_system": False,
            "enable_response_analysis": True,
        }
    )
    assert "null" in appendix
    assert "broken_commitment" not in appendix
from src.ai.thought_prompt import is_thought_prompt_enabled


class _GetSettings:
    def __init__(self, value: bool):
        self._value = value

    def get(self, key: str, default=None):
        if key == "enable_ene_goals":
            return self._value
        if key == "enable_proactive_conversation":
            return self._value
        return default


class _ConfigSettings:
    def __init__(self, value: bool):
        self.config = {"enable_ene_goals": value, "enable_proactive_conversation": value}


class _RaisingGetSettings:
    def __init__(self):
        self.config = {
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
        }

    def get(self, key: str, default=None):
        raise RuntimeError("설정 저장소를 읽을 수 없음")


def test_response_contract_includes_goal_and_thought_sections_when_enabled():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": True, "enable_ene_thoughts": True}
    )

    assert "[analysis]" in appendix
    assert "[ene_goal_update]" in appendix
    assert "create" in appendix
    assert "update" in appendix
    assert "complete" in appendix
    assert "cancel" in appendix
    assert "[subconscious]" in appendix


def test_response_contract_appendix_keeps_legacy_builder_compatibility():
    settings = {"ui_language": "en", "enable_ene_goals": True, "enable_ene_thoughts": True}

    assert build_response_contract_appendix(settings) == build_legacy_response_contract_appendix(settings)


def test_response_contract_goal_format_uses_canonical_key_value_block():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": True, "enable_ene_thoughts": False}
    )

    assert "[ene_goal_update]\naction=none\ntype=short_term\nid=\ntitle=\nreason=\ncompletion_reason=\n[/ene_goal_update]" in appendix
    assert "\nscope=" not in appendix


def test_response_contract_keeps_analysis_when_goal_and_thought_sections_are_disabled():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False}
    )

    assert "[analysis]" in appendix
    assert "[ene_goal_update]" not in appendix
    assert "[subconscious]" not in appendix


def test_response_contract_omits_analysis_when_disabled():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ko",
            "enable_response_analysis": False,
            "enable_ene_goals": True,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
        }
    )

    assert "[analysis]" not in appendix
    assert "[ene_goal_update]" in appendix
    assert "블록 뒤에" not in appendix


def test_response_contract_prefers_proactive_conversation_rules_when_enabled():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False}
    )

    assert "[proactive_conversation]" in appendix
    assert "원칙적으로" in appendix
    assert "quiet-checkin" in appendix
    assert "short-followup" in appendix
    assert "quiet-checkin" in appendix
    assert "topic-reopen" in appendix
    assert "task-momentum" in appendix
    assert "global-proactive" in appendix
    assert "2026-05-26T21:20:00+09:00" not in appendix
    assert "<ISO8601 +09:00" in appendix


def test_response_contract_lists_only_available_proactive_cooldown_keys():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ko",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "proactive_available_cooldown_keys": ["quiet-checkin", "task-momentum"],
        }
    )

    assert "[proactive_conversation]" in appendix
    assert "quiet-checkin, task-momentum" in appendix
    assert "cooldown_key=quiet-checkin" in appendix
    assert "short-followup" not in appendix
    assert "topic-reopen" not in appendix


def test_response_contract_guides_closed_conversations_toward_new_topics():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ko",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
        }
    )

    assert "대화가 자연스럽게 마무리된 흐름이면 기존 화제를 억지로 이어가지 말고" in appendix
    assert "topic-reopen" in appendix
    assert "quiet-checkin" in appendix
    assert "가벼운 새 화제" in appendix


def test_response_contract_localizes_closed_conversation_topic_shift_rule():
    english = build_response_contract_appendix(
        {
            "ui_language": "en",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
        }
    )
    japanese = build_response_contract_appendix(
        {
            "ui_language": "ja",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
        }
    )

    assert "If the conversation has naturally wrapped up" in english
    assert "a light new topic" in english
    assert "会話が自然に一区切りついている場合" in japanese
    assert "軽い新しい話題" in japanese


def test_response_contract_omits_proactive_rules_when_all_keys_are_on_cooldown():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ko",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "proactive_available_cooldown_keys": [],
        }
    )

    assert "[analysis]" in appendix
    assert "[proactive_conversation]" not in appendix
    assert "선제 대화 기능" not in appendix


def test_response_contract_omits_proactive_conversation_rules_when_disabled():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ko",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
        }
    )

    assert "[analysis]" in appendix
    assert "[proactive_conversation]" not in appendix
    assert "short-followup" not in appendix


def test_response_contract_includes_custom_prompt_names_without_changing_parser_tokens():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "en",
            "enable_ene_goals": True,
            "enable_ene_thoughts": True,
            "assistant_display_name": "Luna",
            "user_address_name": "Captain",
        }
    )

    assert "assistant persona as `Luna`" in appendix
    assert "address the user as `Captain`" in appendix
    assert "[ene_goal_update]" in appendix
    assert "[subconscious]" in appendix


def test_response_contract_does_not_mention_tts_token_when_tts_is_omitted():
    appendix = build_response_contract_appendix(
        {
            "ui_language": "ja",
            "tts_language": "ja",
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "assistant_display_name": "ルナ",
            "user_address_name": "船長",
        }
    )

    assert "ルナ" in appendix
    assert "船長" in appendix
    assert "[tts]" not in appendix


def test_goal_prompt_enabled_reads_supported_settings_sources():
    assert is_goal_prompt_enabled() is True
    assert is_goal_prompt_enabled({"enable_ene_goals": False}) is False
    assert is_goal_prompt_enabled(_GetSettings(False)) is False
    assert is_goal_prompt_enabled(_ConfigSettings(False)) is False


def test_proactive_conversation_enabled_reads_supported_settings_sources():
    assert is_proactive_conversation_enabled() is True
    assert is_proactive_conversation_enabled({"enable_proactive_conversation": False}) is False
    assert is_proactive_conversation_enabled(_GetSettings(False)) is False
    assert is_proactive_conversation_enabled(_ConfigSettings(False)) is False


def test_prompt_feature_flags_fall_back_to_config_when_get_raises():
    settings = _RaisingGetSettings()

    assert is_goal_prompt_enabled(settings) is False
    assert is_thought_prompt_enabled(settings) is False
    assert is_proactive_conversation_enabled(settings) is False


def test_goal_update_rules_describe_actions_and_goal_scopes():
    rules = "\n".join(build_goal_update_rules(language="ko"))

    assert "[ene_goal_update]" in rules
    assert "action=none" in rules
    assert "create" in rules
    assert "update" in rules
    assert "complete" in rules
    assert "cancel" in rules
    assert "short_term" in rules
    assert "long_term" in rules
