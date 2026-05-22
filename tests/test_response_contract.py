from src.ai.goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from src.ai.response_contract import build_response_contract_appendix


class _GetSettings:
    def __init__(self, value: bool):
        self._value = value

    def get(self, key: str, default=None):
        if key == "enable_ene_goals":
            return self._value
        return default


class _ConfigSettings:
    def __init__(self, value: bool):
        self.config = {"enable_ene_goals": value}


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


def test_response_contract_keeps_analysis_when_goal_and_thought_sections_are_disabled():
    appendix = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False}
    )

    assert "[analysis]" in appendix
    assert "[ene_goal_update]" not in appendix
    assert "[subconscious]" not in appendix


def test_goal_prompt_enabled_reads_supported_settings_sources():
    assert is_goal_prompt_enabled() is True
    assert is_goal_prompt_enabled({"enable_ene_goals": False}) is False
    assert is_goal_prompt_enabled(_GetSettings(False)) is False
    assert is_goal_prompt_enabled(_ConfigSettings(False)) is False


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
