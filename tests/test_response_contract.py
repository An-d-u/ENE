from src.ai.goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from src.ai.response_contract import build_response_contract_appendix, is_proactive_conversation_enabled
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


def test_response_contract_goal_format_uses_canonical_key_value_block():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": True, "enable_ene_thoughts": False}
    )

    assert "[ene_goal_update]\naction=none\ntype=short_term\nid=\ntitle=\nreason=\ncompletion_reason=\n[/ene_goal_update]" in appendix
    assert "scope=" not in appendix


def test_response_contract_keeps_analysis_when_goal_and_thought_sections_are_disabled():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False}
    )

    assert "[analysis]" in appendix
    assert "[ene_goal_update]" not in appendix
    assert "[subconscious]" not in appendix


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
