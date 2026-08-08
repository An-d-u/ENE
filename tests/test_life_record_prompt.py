from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime
import inspect
from pathlib import Path

import pytest


def _raw_mood(**overrides):
    mood = {
        "current_mood": "calm",
        "temporary_state": "steady",
        "valence": 0.2,
        "energy": -0.1,
        "bond": 0.4,
        "stress": 0.05,
    }
    mood.update(overrides)
    return mood


def _context(*, language="ko", world_markdown="# 별빛 마을\n- 작은 도서관"):
    from src.ai.life_record_prompt import (
        LifeRecordGenerationContext,
        snapshot_life_mood,
    )

    return LifeRecordGenerationContext(
        inactive_started_at=datetime.fromisoformat("2026-08-07T22:30:00+09:00"),
        returned_at=datetime.fromisoformat("2026-08-08T08:00:00+09:00"),
        timezone="Asia/Seoul",
        inactive_start_source="graceful_exit",
        world_markdown=world_markdown,
        ene_identity={"identity": ("별빛 마을의 기록 담당자다.",)},
        relationship_tone=("방문객을 친근하게 대한다.",),
        profile_facts=(
            {"category": "habit", "content": "아침에 광장을 한 바퀴 걷는다."},
        ),
        display_names={"assistant": "루미", "user": "여행자"},
        previous_record={
            "id": "synthetic-previous-record",
            "ending_state": {"place": "작은 도서관", "summary": "책을 정리했다."},
        },
        mood_snapshot=snapshot_life_mood(_raw_mood()),
        language=language,
    )


def test_life_record_profile_export_is_ordered_limited_and_whitelisted():
    from src.ai.ene_profile import EneProfile, EneProfileFact

    profile = EneProfile(profile_file=Path.cwd() / "missing-task6-profile.json")
    profile.core_profile = {
        "identity": ["합성 정체성 A", "합성 정체성 B"],
        "speaking_style": ["SPEAKING_STYLE_SENTINEL"],
        "relationship_tone": ["합성 관계 톤"],
    }
    profile.facts = [
        EneProfileFact("자동 최신", "habit", "2026-08-08T10:00:00", origin="auto"),
        EneProfileFact("수동 이전", "goal", "2026-08-06T10:00:00", origin="manual"),
        EneProfileFact(
            "잠금 수동 이전",
            "basic",
            "2026-08-05T10:00:00",
            origin="manual",
            auto_update=False,
        ),
        EneProfileFact(
            "잠금 수동 최신",
            "relationship_tone",
            "2026-08-07T10:00:00",
            origin="manual",
            auto_update=False,
        ),
        EneProfileFact("수동 최신", "preference", "2026-08-08T09:00:00", origin="manual"),
        EneProfileFact("자동 이전", "habit", "2026-08-07T09:00:00", origin="auto"),
        EneProfileFact("SPEAKING_FACT_SENTINEL", "speaking_style", "2026-08-09T10:00:00"),
    ]

    exported = profile.export_life_record_profile(max_facts=5)

    assert exported == {
        "ene_identity": {"identity": ("합성 정체성 A", "합성 정체성 B")},
        "relationship_tone": ("합성 관계 톤",),
        "profile_facts": (
            {"category": "relationship_tone", "content": "잠금 수동 최신"},
            {"category": "basic", "content": "잠금 수동 이전"},
            {"category": "preference", "content": "수동 최신"},
            {"category": "goal", "content": "수동 이전"},
            {"category": "habit", "content": "자동 최신"},
        ),
    }
    assert "SPEAKING_STYLE_SENTINEL" not in repr(exported)
    assert "SPEAKING_FACT_SENTINEL" not in repr(exported)


def test_life_record_profile_export_defaults_to_ten_facts():
    from src.ai.ene_profile import EneProfile, EneProfileFact

    profile = EneProfile(profile_file=Path.cwd() / "missing-task6-profile.json")
    profile.facts = [
        EneProfileFact(f"합성 습관 {index}", "habit", f"2026-08-{index + 1:02d}T09:00:00")
        for index in range(12)
    ]

    assert len(profile.export_life_record_profile()["profile_facts"]) == 10


def test_snapshot_life_mood_copies_only_exact_canonical_source_fields():
    from src.ai.life_record_prompt import snapshot_life_mood

    raw = _raw_mood()
    snapshot = snapshot_life_mood(raw)
    raw["valence"] = 0.9

    assert asdict(snapshot) == {
        "label": "calm",
        "valence": 0.2,
        "energy": -0.1,
        "bond": 0.4,
        "stress": 0.05,
        "short_term_mood": "steady",
    }
    with pytest.raises(FrozenInstanceError):
        snapshot.label = "cheerful"
    assert "calm" not in repr(snapshot)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda mood: mood.pop("stress"),
        lambda mood: mood.update({"profile": "PRIVATE_PROFILE_SENTINEL"}),
        lambda mood: mood.update({"expression_traits": {"warmth": 0.8}}),
        lambda mood: mood.update({"updated_at": "2026-08-08T08:00:00+09:00"}),
    ],
)
def test_snapshot_life_mood_rejects_missing_or_additional_fields(mutation):
    from src.ai.life_record_prompt import snapshot_life_mood

    raw = _raw_mood()
    mutation(raw)

    with pytest.raises(ValueError, match="invalid_mood_fields"):
        snapshot_life_mood(raw)


@pytest.mark.parametrize("field", ["current_mood", "temporary_state"])
def test_snapshot_life_mood_rejects_unknown_codes(field):
    from src.ai.life_record_prompt import snapshot_life_mood

    with pytest.raises(ValueError, match="invalid_mood_code"):
        snapshot_life_mood(_raw_mood(**{field: "번역된 기분 문장"}))


@pytest.mark.parametrize("field", ["valence", "energy", "bond", "stress"])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), float("-inf"), "0.2"])
def test_snapshot_life_mood_rejects_non_finite_or_non_numeric_axes(field, value):
    from src.ai.life_record_prompt import snapshot_life_mood

    with pytest.raises(ValueError, match="invalid_mood_number"):
        snapshot_life_mood(_raw_mood(**{field: value}))


@pytest.mark.parametrize(
    ("language", "language_rule"),
    [
        ("ko", "activity와 ending_state의 자연어 값은 한국어"),
        ("en", "natural-language values in activity and ending_state in English"),
        ("ja", "activityとending_stateの自然言語値は日本語"),
    ],
)
def test_prompt_contains_only_life_record_context_and_full_generation_contract(
    language, language_rule
):
    from src.ai.life_record_prompt import build_life_record_prompt

    prompt = build_life_record_prompt(_context(language=language))

    for expected in (
        "# 별빛 마을",
        "별빛 마을의 기록 담당자다.",
        "방문객을 친근하게 대한다.",
        "아침에 광장을 한 바퀴 걷는다.",
        '"assistant": "루미"',
        '"user": "여행자"',
        "2026-08-07T22:30:00+09:00",
        "2026-08-08T08:00:00+09:00",
        "Asia/Seoul",
        "2026-08-07 (Friday)",
        "2026-08-08 (Saturday)",
        "synthetic-previous-record",
        '"label": "calm"',
        '"short_term_mood": "steady"',
        "graceful_exit",
        "최대 24개",
        "전체 비활성 구간",
        "30분에서 수시간",
        language_rule,
    ):
        assert expected in prompt

    assert "사용자는 inactive_started_at부터 returned_at 직전까지 돌아오지 않았다" in prompt
    assert "복귀를 확인하는 행동은 returned_at 전에 배치하지 않는다" in prompt
    assert "base_system_prompt" not in prompt


@pytest.mark.parametrize(
    ("returned_at", "expected_rule"),
    [
        ("2026-08-10T22:30:00+09:00", "수시간에서 하루"),
        ("2026-08-18T22:30:00+09:00", "여러 날 단위"),
    ],
)
def test_prompt_selects_interval_granularity(returned_at, expected_rule):
    from dataclasses import replace

    from src.ai.life_record_prompt import build_life_record_prompt

    context = replace(_context(), returned_at=datetime.fromisoformat(returned_at))

    assert expected_rule in build_life_record_prompt(context)


def test_empty_world_stops_prompt_building_before_llm_call():
    from src.ai.life_record_prompt import LifeWorldEmptyError, build_life_record_prompt

    with pytest.raises(LifeWorldEmptyError):
        build_life_record_prompt(_context(world_markdown=" \n\t"))


def test_context_and_builder_signature_exclude_private_general_chat_inputs():
    from src.ai.life_record_prompt import (
        LifeRecordGenerationContext,
        build_life_record_prompt,
    )

    forbidden = {
        "speaking_style",
        "user_profile",
        "conversation",
        "long_term_memory",
        "calendar",
        "attachments",
        "first_chat_body",
        "sub_prompt",
        "response_contract",
        "analysis_appendix",
        "memory_context",
        "base_system_prompt",
        "regeneration_target",
    }

    assert forbidden.isdisjoint(LifeRecordGenerationContext.__dataclass_fields__)
    assert forbidden.isdisjoint(inspect.signature(build_life_record_prompt).parameters)
    assert "별도 system instruction" not in build_life_record_prompt(_context())


def test_prompt_reapplies_nested_profile_and_name_whitelists():
    from dataclasses import replace

    from src.ai.life_record_prompt import build_life_record_prompt

    context = replace(
        _context(),
        ene_identity={
            "identity": ("합성 정체성",),
            "speaking_style": ("NESTED_SPEAKING_SENTINEL",),
            "user_profile": "NESTED_USER_PROFILE_SENTINEL",
        },
        profile_facts=(
            {
                "category": "habit",
                "content": "합성 산책 습관",
                "source": "NESTED_SOURCE_SENTINEL",
            },
            {"category": "speaking_style", "content": "NESTED_FACT_SENTINEL"},
        ),
        display_names={
            "assistant": "루미",
            "user": "여행자",
            "profile": "NESTED_NAME_PROFILE_SENTINEL",
        },
    )

    prompt = build_life_record_prompt(context)

    assert "합성 정체성" in prompt
    assert "합성 산책 습관" in prompt
    for sentinel in (
        "NESTED_SPEAKING_SENTINEL",
        "NESTED_USER_PROFILE_SENTINEL",
        "NESTED_SOURCE_SENTINEL",
        "NESTED_FACT_SENTINEL",
        "NESTED_NAME_PROFILE_SENTINEL",
    ):
        assert sentinel not in prompt
