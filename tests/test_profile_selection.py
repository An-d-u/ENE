"""같은 개수 제한에서 오래된 관련 사실과 비교 대상 ID를 보존한다."""

from copy import deepcopy
from types import SimpleNamespace
import pytest

from src.ai.user_profile import ProfileFact


def facts_with_noise():
    old = ProfileFact("격자 모형 조립을 보류했다.", "goal", "2025-01-01", subject="격자 모형", state="paused", id="relevant")
    noise = [ProfileFact(f"연습 부품 {i}의 재질은 종이다.", "goal", f"2025-02-{i+1:02}", id=f"noise-{i}") for i in range(25)]
    return [old, *noise]


@pytest.mark.parametrize("kind,limit", [("response", 10), ("summary", 20)])
def test_old_relevant_fact_survives_more_than_twenty_recent_facts(kind, limit):
    from src.ai.profile_selection import select_response_facts, select_summary_facts
    facts = facts_with_noise()
    before = deepcopy(facts)
    select = select_response_facts if kind == "response" else select_summary_facts
    selected = select(facts, "격자 모형 조립 상태는?", limit)
    assert selected[0].id == "relevant"
    assert selected[0].state == "paused"
    assert len(selected) == limit
    assert facts == before


def test_no_specific_cue_preserves_recent_order_and_zero_is_unlimited():
    from src.ai.profile_selection import select_response_facts
    facts = facts_with_noise()
    assert select_response_facts(facts, "목표 상태를 알려줘.", 10)[0].id == "noise-24"
    assert len(select_response_facts(facts, "", 0)) == 26


def test_duplicate_ids_and_bad_dates_are_stable():
    from src.ai.profile_selection import select_summary_facts
    facts = facts_with_noise()[:3]
    facts[1].timestamp = "잘못된 날짜"
    facts[2].timestamp = ""
    assert [fact.id for fact in select_summary_facts([*facts, facts[0]], "")] == ["relevant", "noise-0", "noise-1"]


def test_summary_compares_only_user_turns():
    from src.ai.summary_prompt import build_summary_prompt
    profile = SimpleNamespace(get_all_facts=facts_with_noise)
    assistant_only = build_summary_prompt([("user", "새로운 소식을 이야기하자."), ("assistant", "격자 모형 상태는 어떤가요?")], user_profile=profile)
    user_context = build_summary_prompt([("user", "격자 모형 조립을 다시 시작한다.")], user_profile=profile)
    assert "id: relevant;" not in assistant_only.prompt
    assert "id: relevant;" in user_context.prompt
