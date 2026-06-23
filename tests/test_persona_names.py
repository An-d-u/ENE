from src.ai.persona_names import resolve_prompt_persona_names, role_label_for_prompt


def test_resolve_prompt_persona_names_uses_language_defaults():
    names = resolve_prompt_persona_names(language="ja")

    assert names.assistant == "エネ"
    assert names.user == "マスター"


def test_resolve_prompt_persona_names_uses_custom_settings():
    settings = {
        "ui_language": "en",
        "assistant_display_name": "Luna",
        "user_address_name": "Captain",
    }

    names = resolve_prompt_persona_names(settings_source=settings)

    assert names.assistant == "Luna"
    assert names.user == "Captain"
    assert role_label_for_prompt("assistant", settings_source=settings) == "Luna"
    assert role_label_for_prompt("user", settings_source=settings) == "Captain"
