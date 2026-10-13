"""대상 연결과 검토 지문은 UI·모델 메타데이터와 분리한다."""

from copy import deepcopy
import pytest

from src.ai.user_profile import ProfileFact, UserProfile


def setup_change(tmp_path, subject="청색 블록"):
    profile = UserProfile(tmp_path / "profile.json")
    fact = ProfileFact("청색 블록은 조립 중이다.", "goal", "2025-01-01", id="block", subject=subject)
    profile.facts = [fact]
    update = dict(category="goal", content="청색 블록을 완성했다.", subject="청색 블록",
                  state="completed", assertion="current", evidence="청색 블록을 완성했다.",
                  replaces="block", effective_at="2025-02-01")
    return profile, fact, update


def apply(profile, update, context=None):
    profile.apply_summary_facts(
        [f"[{update['category']}] {update['content']}"], [update],
        original_messages=[dict(role="user", text="청색 블록을 완성했다.")],
        observed_at="2025-02-02", source_memory_id="summary-1", reviewed=True,
        review_context=context,
    )


def test_mismatched_target_cannot_be_authorized_by_manual_edit_flag(tmp_path):
    profile, fact, update = setup_change(tmp_path, "황색 블록")
    old = fact.to_dict()
    update["manual_edit"] = True
    apply(profile, update)
    assert fact.to_dict() == old


def test_subject_only_edit_requires_explicit_confirmation(tmp_path):
    from src.ai.profile_review import make_proposals, review_proposal
    profile, fact, update = setup_change(tmp_path)
    update.update(content=fact.content, state=fact.state, subject="청록 블록")
    proposal = make_proposals(profile.facts, [update])[0]
    unconfirmed = review_proposal(proposal)
    apply(profile, unconfirmed.update, [unconfirmed])
    assert fact.subject == "청색 블록"
    confirmed = review_proposal(proposal, confirm_subject=True)
    apply(profile, confirmed.update, [confirmed])
    assert fact.subject == "청록 블록"
    assert len(fact.history) == 1


@pytest.mark.parametrize("change", ["content", "history", "delete"])
def test_stale_snapshot_requires_refresh(tmp_path, change):
    from src.ai.profile_review import make_proposals, review_proposal
    profile, fact, update = setup_change(tmp_path)
    reviewed = review_proposal(make_proposals(profile.facts, [update])[0])
    if change == "delete":
        profile.facts.clear()
    elif change == "history":
        fact.history.append({"content": "합성 이전 상태"})
    else:
        fact.content = "별도 편집이 반영됐다."
    assert reviewed.decision(profile.facts) == "refresh"
    before = deepcopy([item.to_dict() for item in profile.facts])
    apply(profile, reviewed.update, [reviewed])
    assert [item.to_dict() for item in profile.facts] == before


def test_legacy_blank_subject_requires_review_link_confirmation(tmp_path):
    from src.ai.profile_review import make_proposals, review_proposal
    profile, fact, update = setup_change(tmp_path, "")
    apply(profile, update)
    assert fact.subject == ""
    reviewed = review_proposal(make_proposals(profile.facts, [update])[0], confirm_subject=True)
    apply(profile, reviewed.update, [reviewed])
    assert fact.subject == "청색 블록"


def test_fingerprint_is_stable_and_covers_source_and_history(tmp_path):
    from src.ai.profile_review import fact_fingerprint
    _, fact, _ = setup_change(tmp_path)
    before = fact_fingerprint(fact)
    assert fact_fingerprint(dict(reversed(list(fact.to_dict().items())))) == before
    fact.source = "새 합성 근거"
    assert fact_fingerprint(fact) != before


def test_strict_save_reports_real_write_failure(tmp_path, monkeypatch):
    profile, _, _ = setup_change(tmp_path)
    monkeypatch.setattr("src.ai.user_profile.save_json_data", lambda *a, **kw: (_ for _ in ()).throw(OSError("합성 저장 실패")))
    with pytest.raises(OSError):
        profile.save(strict=True)
