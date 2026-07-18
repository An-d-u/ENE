import pytest

from src.ai import prompt as prompt_module
from src.ai import prompt_config
from src.ai.response_envelope import get_response_envelope_v1_schema
from src.ai.response_protocol import LLMRequestKind, ResponseMode


LEGACY_TOKENS = (
    "[emotion]",
    "[analysis]",
    "[subconscious]",
    "[tts]",
    "[ene_goal_update]",
    "[proactive_conversation]",
    "[event:",
    "[약속:",
    "[gesture:",
)


def all_enabled_settings() -> dict:
    return {
        "ui_language": "en",
        "tts_language": "ja",
        "enable_response_analysis": True,
        "enable_schedule_recognition": True,
        "enable_conversation_promises": True,
        "enable_ene_goals": True,
        "enable_ene_thoughts": True,
        "enable_proactive_conversation": True,
        "enable_synthetic_gestures": True,
        "proactive_available_cooldown_keys": ["quiet-checkin", "task-momentum"],
    }


def _install_synthetic_prompt_config(monkeypatch) -> None:
    config = {
        "base_system_prompt": "Synthetic base prompt.",
        "sub_prompt_body": "Keep the reply concise and neutral.",
        "emotions": ["normal", "smile"],
        "emotion_guides": {
            "normal": "Use for a neutral reply.",
            "smile": "Use for a warm reply.",
        },
    }
    monkeypatch.setattr(
        prompt_module, "load_runtime_prompt_config", lambda **_kwargs: config
    )
    monkeypatch.setattr(
        prompt_config, "load_runtime_prompt_config", lambda **_kwargs: config
    )


@pytest.mark.parametrize(
    "response_mode",
    [ResponseMode.JSON_SCHEMA, ResponseMode.STRICT_TOOL, ResponseMode.JSON_OBJECT],
)
def test_runtime_structured_final_prompt_uses_fields_without_legacy_tokens(
    monkeypatch,
    response_mode,
):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=response_mode,
        settings_source=all_enabled_settings(),
    )

    assert all(token not in prompt for token in LEGACY_TOKENS)
    for field in get_response_envelope_v1_schema()["required"]:
        assert f"`{field}`" in prompt


def test_runtime_structured_final_prompt_includes_analysis_semantics_once(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=all_enabled_settings(),
    )

    assert prompt.count("### Internal Analysis Semantic Rules") == 1


def test_runtime_legacy_final_prompt_preserves_tag_contract(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.LEGACY_TAGS,
        settings_source=all_enabled_settings(),
    )

    assert "[subconscious]" in prompt
    assert "[ene_goal_update]" in prompt


@pytest.mark.parametrize(
    "request_kind",
    [
        LLMRequestKind.SUMMARY,
        LLMRequestKind.DECISION,
        LLMRequestKind.MARKDOWN,
        LLMRequestKind.PLAIN_TEXT,
    ],
)
def test_plain_text_with_sub_prompt_has_no_final_response_contract(
    monkeypatch, request_kind
):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        request_kind=request_kind,
        response_mode=ResponseMode.LEGACY_TAGS,
        settings_source=all_enabled_settings(),
    )

    assert "Synthetic base prompt." in prompt
    assert "Keep the reply concise and neutral." in prompt
    assert all(token not in prompt for token in LEGACY_TOKENS)
    assert "Final Response Format" not in prompt


def test_final_contract_is_selected_by_request_kind_not_include_sub_prompt(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=False,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=all_enabled_settings(),
    )

    assert prompt.startswith("Synthetic base prompt.")
    assert "`reply`" in prompt
    assert "`emotion`" in prompt
    assert all(token not in prompt for token in LEGACY_TOKENS)


def test_legacy_final_contract_is_kept_without_sub_prompt(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=False,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.LEGACY_TAGS,
        settings_source=all_enabled_settings(),
    )

    assert prompt.startswith("Synthetic base prompt.")
    assert "[subconscious]" in prompt
    assert "[ene_goal_update]" in prompt


def test_structured_sub_prompt_uses_emotion_field_instead_of_emotion_tag():
    prompt = prompt_config.build_sub_prompt_text(
        "Keep the reply concise and neutral.",
        ["normal", "smile"],
        {"normal": "Neutral reply.", "smile": "Warm reply."},
        language="en",
        response_style="structured_fields",
    )

    assert "`emotion`" in prompt
    assert "[emotion]" not in prompt


def test_structured_thought_rule_excludes_raw_reasoning(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)

    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=all_enabled_settings(),
    ).lower()

    assert "`thought`" in prompt
    assert "not raw reasoning" in prompt
    assert "do not provide step-by-step reasoning" in prompt


def test_structured_disabled_features_still_describe_required_empty_values(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)
    settings = all_enabled_settings()
    settings.update(
        {
            "enable_response_analysis": False,
            "enable_schedule_recognition": False,
            "enable_conversation_promises": False,
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
            "enable_synthetic_gestures": False,
        }
    )

    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=settings,
    )

    for field in get_response_envelope_v1_schema()["required"]:
        assert f"`{field}`" in prompt
    assert "empty string" in prompt
    assert "empty array" in prompt
    assert "empty object" in prompt
    assert "set `action` to `none`" in prompt


def test_json_object_contract_describes_exact_canonical_layout(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)
    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=False,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_OBJECT,
        settings_source=all_enabled_settings(),
    )

    expected_layout = (
        "- `reply`: string",
        "- `emotion`: string",
        "- `tts_text`: string",
        "- `events`: array of objects with exactly {`date`: string, `title`: string, `description`: string}",
        "- `analysis`: object with exactly {`user_emotion`: string, `user_intent`: string, `interaction_effect`: string, `bond_delta_hint`: string, `stress_delta_hint`: string, `energy_delta_hint`: string, `valence_delta_hint`: string, `confidence`: string, `flags`: string}",
        "- `promises`: array of objects with exactly {`trigger_at`: string, `title`: string, `source`: string, `source_excerpt`: string}",
        "- `thought`: string",
        "- `goal_update`: object with exactly {`action`: string, `type`: string, `id`: string, `title`: string, `reason`: string, `completion_reason`: string}",
        "- `proactive_conversations`: array of objects with exactly {`trigger_at`: string, `title`: string, `generation_prompt`: string, `source_excerpt`: string, `reason`: string, `cooldown_key`: string}",
        "- `gesture`: string",
    )
    for line in expected_layout:
        assert line in prompt
    assert "All listed fields are required at every level; do not add extra fields." in prompt
    assert "supplied strict response envelope schema" not in prompt
    assert "Do not use an empty object" in prompt


def test_structured_final_without_sub_prompt_lists_active_emotions(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)
    prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=False,
        request_kind="final_reply",
        response_mode="json_object",
        settings_source=all_enabled_settings(),
    )
    assert "Allowed emotions: `normal`, `smile`." in prompt


@pytest.mark.parametrize("value", [None, "", "final-reply", "summary_typo"])
def test_runtime_prompt_rejects_invalid_request_kind(monkeypatch, value):
    _install_synthetic_prompt_config(monkeypatch)
    with pytest.raises(ValueError, match="request kind"):
        prompt_module.build_runtime_system_prompt(
            request_kind=value,
            response_mode=ResponseMode.JSON_OBJECT,
            settings_source=all_enabled_settings(),
        )


@pytest.mark.parametrize("value", [None, "", "json", "legacy"])
def test_runtime_prompt_rejects_invalid_response_mode(monkeypatch, value):
    _install_synthetic_prompt_config(monkeypatch)
    with pytest.raises(ValueError, match="response mode"):
        prompt_module.build_runtime_system_prompt(
            request_kind=LLMRequestKind.FINAL_REPLY,
            response_mode=value,
            settings_source=all_enabled_settings(),
        )


def test_public_prompt_builders_reject_unknown_response_style(monkeypatch):
    from src.ai.analysis_prompt import build_analysis_system_appendix
    from src.ai.goal_prompt import build_goal_update_rules
    from src.ai.sub_prompt import get_sub_prompt
    from src.ai.thought_prompt import build_thought_rules

    _install_synthetic_prompt_config(monkeypatch)
    builders = (
        lambda: prompt_module.get_system_prompt(response_style="typo"),
        lambda: prompt_config.build_sub_prompt_text(
            "Neutral body.", ["normal"], {"normal": "Neutral."}, response_style="typo"
        ),
        lambda: prompt_config.get_sub_prompt_text(response_style="typo"),
        lambda: get_sub_prompt(response_style="typo"),
        lambda: build_analysis_system_appendix(response_style="typo"),
        lambda: build_goal_update_rules(response_style="typo"),
        lambda: build_thought_rules(response_style="typo"),
    )
    for builder in builders:
        with pytest.raises(ValueError, match="response style"):
            builder()


def test_structured_english_preserves_legacy_semantic_rules(monkeypatch):
    _install_synthetic_prompt_config(monkeypatch)
    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=all_enabled_settings(),
    )
    required_semantics = (
        "Use only `high_negative`, `low_negative`, `none`, `low_positive`, or `high_positive`",
        "Separate multiple `flags` values with commas.",
        "use `interaction_effect=mixed` and low `confidence`",
        "Interpret relative dates from the current date.",
        "Do not record past, uncertain, or completed schedules.",
        "Even in a cold or sensitive state, do not become rude or aggressive.",
        "Even in a warm state, do not become overly dramatic or clingy.",
        "If an important upcoming schedule is approaching and incomplete, give a brief gentle reminder.",
        "A plain mention of the current time is not a promise.",
        "Record only a real future commitment or concrete agreement.",
        "Keep each promise `title` concise and natural; do not copy the source sentence.",
        "If the promise is already stored, avoid repeatedly mentioning time in normal replies.",
        "set `source` to `assistant`",
        "Support both relative and absolute times",
        "vague, past, joking, or hopeful",
        "at most one item in `promises`",
        "When the conversation is still open, prefer a follow-up that continues the existing context.",
        "do not force the previous topic to continue",
        "a light new topic, mood shift, or gentle check-in",
        "For a closed conversation, `cooldown_key` must be one of: quiet-checkin.",
        "Do not create a proactive follow-up when the reply already creates a promise or reminder.",
        "`trigger_at` must be ISO 8601 with `+09:00`",
        "`generation_prompt` is an instruction for the later reply",
        "`source_excerpt` must be a short synthetic context summary",
        "`cooldown_key` must be one of: quiet-checkin, task-momentum.",
        "For `create`, require `type`, `title`, and `reason`.",
        "For `update`, require `id` and at least one of `title` or `reason`.",
        "For `complete` or `cancel`, require `id`",
    )
    for rule in required_semantics:
        assert rule in prompt
    assert "For a closed conversation, `cooldown_key` must be one of: task-momentum" not in prompt
    assert all(token not in prompt for token in LEGACY_TOKENS)


@pytest.mark.parametrize(
    ("language", "tts_language", "expected_rules"),
    [
        (
            "ko",
            "ja",
            (
                "현재 날짜를 기준",
                "차갑거나 예민한 상태",
                "무례하거나 공격적",
                "따뜻한 상태",
                "중요한 임박 일정",
                "단순한 현재 시각 언급",
                "`title`은 짧고 자연스럽게",
                "이미 저장된 약속",
                "대화가 아직 열린",
                "이전 화제를 억지로",
                "약속이나 알림",
                "`trigger_at`은 현재 시각과 대화 문맥",
                "닫힌 대화의 `cooldown_key`는 다음 중 하나만 사용하세요: quiet-checkin.",
                "일본어",
                "### 정규 응답 구조",
                "객체이며 정확히 다음 필드만 포함",
            ),
        ),
        (
            "ja",
            "ko",
            (
                "現在の日付",
                "冷たい、または敏感な状態",
                "無礼または攻撃的",
                "温かい状態",
                "重要な予定が目前",
                "現在時刻に触れただけ",
                "`title` は短く自然に",
                "すでに保存された約束",
                "会話がまだ続いている",
                "以前の話題を無理",
                "約束またはリマインダー",
                "`trigger_at` は現在時刻と会話文脈",
                "終了した会話の `cooldown_key` は次のいずれかだけにしてください: quiet-checkin.",
                "韓国語",
                "### 正規応答構造",
                "次のフィールドだけを持つオブジェクト",
            ),
        ),
    ],
)
def test_structured_locales_preserve_semantics_without_legacy_tokens(
    monkeypatch, language, tts_language, expected_rules
):
    _install_synthetic_prompt_config(monkeypatch)
    settings = all_enabled_settings()
    settings.update({"ui_language": language, "tts_language": tts_language})
    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_OBJECT,
        settings_source=settings,
    )
    for rule in expected_rules:
        assert rule in prompt
    for english in (
        "Analysis is disabled",
        "Proactive conversation is disabled",
        "Put at most one of",
        "Canonical response layout",
        "object with exactly",
        "array of objects with exactly",
    ):
        assert english not in prompt
    closed_marker = "닫힌 대화의" if language == "ko" else "終了した会話の"
    closed_key_rule = next(line for line in prompt.splitlines() if closed_marker in line)
    assert "task-momentum" not in closed_key_rule
    assert all(token not in prompt for token in LEGACY_TOKENS)


@pytest.mark.parametrize(
    ("language", "expected_disabled_rules"),
    [
        (
            "ko",
            (
                "분석 기능이 꺼져 있습니다.",
                "일정 인식 기능이 꺼져 있습니다.",
                "약속 인식 기능이 꺼져 있습니다.",
                "목표 기능이 꺼져 있습니다.",
                "생각 기능이 꺼져 있습니다.",
                "선제 대화 기능이 꺼져 있습니다.",
                "제스처 기능이 꺼져 있습니다.",
            ),
        ),
        (
            "ja",
            (
                "分析機能は無効です。",
                "予定認識は無効です。",
                "約束認識は無効です。",
                "目標機能は無効です。",
                "思考機能は無効です。",
                "先回り会話は無効です。",
                "ジェスチャー機能は無効です。",
            ),
        ),
    ],
)
def test_structured_disabled_features_are_localized(
    monkeypatch,
    language,
    expected_disabled_rules,
):
    _install_synthetic_prompt_config(monkeypatch)
    settings = all_enabled_settings()
    settings.update(
        {
            "ui_language": language,
            "tts_language": language,
            "enable_response_analysis": False,
            "enable_schedule_recognition": False,
            "enable_conversation_promises": False,
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
            "enable_synthetic_gestures": False,
        }
    )
    prompt = prompt_module.build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_OBJECT,
        settings_source=settings,
    )

    for rule in expected_disabled_rules:
        assert rule in prompt
    for english_rule in (
        "Analysis is disabled",
        "Schedule recognition is disabled",
        "Promise recognition is disabled",
        "Goals are disabled",
        "Thoughts are disabled",
        "Proactive conversation is disabled",
        "Gestures are disabled",
    ):
        assert english_rule not in prompt
    assert all(token not in prompt for token in LEGACY_TOKENS)


def test_native_repair_prompt_contains_only_requested_field_context():
    from src.ai.response_contract import build_response_repair_prompt

    prompt = build_response_repair_prompt(
        preserved_reply="검증된 합성 답변",
        response_language="ko",
        tts_language="ja",
        repair_fields=("thought",),
        response_mode=ResponseMode.JSON_SCHEMA,
    )

    assert "검증된 합성 답변" in prompt
    assert "ko" in prompt
    assert "ja" in prompt
    assert "`thought`" in prompt
    assert "`tts_text`" not in prompt
    assert all(token not in prompt for token in LEGACY_TOKENS)
    for forbidden in (
        "history",
        "memory",
        "image",
        "profile",
        "emotion",
        "analysis",
        "event",
        "promise",
        "goal",
        "proactive",
        "gesture",
    ):
        assert forbidden not in prompt.lower()


@pytest.mark.parametrize(
    ("fields", "present_tokens", "absent_tokens"),
    [
        (("thought",), ("[subconscious]", "[/subconscious]"), ("[tts]", "[/tts]")),
        (("tts_text",), ("[tts]", "[/tts]"), ("[subconscious]", "[/subconscious]")),
    ],
    ids=("thought-only", "tts-only"),
)
def test_legacy_repair_prompt_uses_only_requested_minimal_blocks(
    fields,
    present_tokens,
    absent_tokens,
):
    from src.ai.response_contract import build_response_repair_prompt

    prompt = build_response_repair_prompt(
        preserved_reply="검증된 합성 답변",
        response_language="ko",
        tts_language="ja",
        repair_fields=fields,
        response_mode=ResponseMode.LEGACY_TAGS,
    )

    assert all(token in prompt for token in present_tokens)
    assert all(token not in prompt for token in absent_tokens)
    for forbidden in (
        "[emotion]",
        "[analysis]",
        "[event:",
        "[약속:",
        "[ene_goal_update]",
        "[proactive_conversation]",
        "[gesture:",
    ):
        assert forbidden not in prompt


def test_repair_prompt_rejects_unknown_fields_and_modes():
    from src.ai.response_contract import build_response_repair_prompt

    with pytest.raises(ValueError, match="repair fields"):
        build_response_repair_prompt(
            preserved_reply="검증된 합성 답변",
            response_language="ko",
            tts_language="ja",
            repair_fields=("reply",),
            response_mode=ResponseMode.JSON_SCHEMA,
        )
    with pytest.raises(ValueError, match="response mode"):
        build_response_repair_prompt(
            preserved_reply="검증된 합성 답변",
            response_language="ko",
            tts_language="ja",
            repair_fields=("thought",),
            response_mode="synthetic-mode",
        )
