import json

from src.ai.user_profile import ProfileFact, UserProfile


def _seed(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")
    profile.facts = [ProfileFact("작업할 때 긴 도표 설명을 선호한다.", "preference", "2026-01-01T10:00:00+09:00")]
    profile.preferences["likes"] = [profile.facts[0].content, "수동 항목"]
    return profile


def _change(profile, **overrides):
    update = {
        "content": "간단한 도표를 선호한다.", "category": "preference",
        "subject": "설명 방식", "replaces": profile.facts[0].id,
        "state": "active", "assertion": "current",
        "effective_at": "2026-02-01T10:00:00+09:00",
        "evidence": "앞으로는 간단한 도표로 설명해 줘.",
    }
    update.update(overrides)
    return update


def _apply(profile, update, *, selected=True, role="user"):
    profile.apply_summary_facts(
        [f"[{update['category']}] {update['content']}"] if selected else [],
        [update],
        original_messages=[{"role": role, "text": update["evidence"]}],
        source="가상 대화", source_memory_id="memory-example",
        observed_at="2026-02-01T11:00:00+09:00",
    )


def test_shorter_explicit_correction_preserves_history_and_syncs_preferences(tmp_path):
    profile = _seed(tmp_path)
    old = profile.facts[0].content
    update = _change(profile)
    _apply(profile, update)
    _apply(profile, update)
    loaded = UserProfile(profile.profile_file)
    assert len(loaded.facts) == 1
    assert loaded.facts[0].content == update["content"]
    assert [item["content"] for item in loaded.facts[0].history] == [old]
    assert loaded.facts[0].source_memory_id == "memory-example"
    assert loaded.preferences["likes"] == ["수동 항목", update["content"]]


def test_historical_or_uncertain_claim_cannot_replace_current_profile(tmp_path):
    for assertion in ("historical", "uncertain"):
        profile = _seed(tmp_path)
        old = profile.facts[0].content
        _apply(profile, _change(profile, assertion=assertion))
        assert len(profile.facts) == 1
        assert profile.facts[0].content == old


def test_older_effective_time_does_not_reverse_current_state(tmp_path):
    profile = _seed(tmp_path)
    _apply(profile, _change(profile, effective_at="2025-01-01"))
    assert profile.facts[0].content == "작업할 때 긴 도표 설명을 선호한다."


def test_unselected_or_assistant_only_evidence_does_not_update(tmp_path):
    profile = _seed(tmp_path)
    old = profile.facts[0].content
    update = _change(profile)
    _apply(profile, update, selected=False)
    _apply(profile, update, role="assistant")
    assert profile.facts[0].content == old


def test_deleted_target_is_not_recreated_by_delayed_summary(tmp_path):
    profile = _seed(tmp_path)
    update = _change(profile)
    profile.delete_fact(0)
    _apply(profile, update)
    assert profile.facts == []
    assert profile.preferences["likes"] == ["수동 항목"]


def test_goal_cancellation_has_state_and_previous_evidence(tmp_path):
    profile = _seed(tmp_path)
    profile.facts[0].category = "goal"
    _apply(profile, _change(profile, category="goal", state="cancelled", content="모형 제작 계획을 취소했다."))
    assert profile.facts[0].state == "cancelled"
    assert "cancelled" in profile.get_context_string()


def test_legacy_fact_ids_are_stable_without_migration_write(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"facts": [{"content": "가상 관찰", "category": "habit", "timestamp": "2026-01-01"}]}), encoding="utf-8")
    before = path.read_bytes()
    first = UserProfile(path)
    second = UserProfile(path)
    assert first.facts[0].id == second.facts[0].id
    assert first.facts[0].id
    assert path.read_bytes() == before


def test_manual_review_edit_replaces_target_only_when_reviewed(tmp_path):
    profile = _seed(tmp_path)
    update = _change(profile, content="대신 표로 설명하는 방식을 선호한다.", evidence="", manual_edit=True)
    _apply(profile, update)
    assert profile.facts[0].content != update["content"]
    profile.apply_summary_facts(
        [f"[preference] {update['content']}"], [update], original_messages=[],
        observed_at="2026-02-01T11:00:00+09:00", reviewed=True,
    )
    assert profile.facts[0].content == update["content"]


def test_invalid_update_content_does_not_abort_other_valid_updates(tmp_path):
    profile = _seed(tmp_path)
    update = _change(profile)
    profile.apply_summary_facts(
        [f"[preference] {update['content']}"], [{**update, "content": {"invalid": True}}, update],
        original_messages=[{"role": "user", "text": update["evidence"]}],
        observed_at="2026-02-01T11:00:00+09:00",
    )
    assert profile.facts[0].content == update["content"]


def test_legacy_summary_without_evidence_cannot_change_current_basic_info(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")
    profile.basic_info["occupation"] = "가상 역할 A"
    profile.apply_summary_facts(
        ["[basic] 직업: 오래전에 맡았던 가상 역할 B"], None,
        original_messages=[], source="가상 과거 회상",
    )
    assert profile.basic_info["occupation"] == "가상 역할 A"
    assert profile.facts == []


def test_new_confirmation_blocks_delayed_older_change_without_new_history(tmp_path):
    profile = _seed(tmp_path)
    old = profile.facts[0].content
    _apply(profile, _change(profile, content=old))
    assert profile.facts[0].history == []
    _apply(profile, _change(profile, effective_at="2026-01-15"))
    assert profile.facts[0].content == old
