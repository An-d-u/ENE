"""합성 평가 자료의 정답과 근거 연결을 검사한다."""

import json
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).parent / "fixtures" / "memory_quality"
GROUPS = {"profile", "followup", "temporal", "raw_detail", "assertion", "abstention", "multi_memory", "boundary"}


@pytest.mark.parametrize("filename,count,per_group", [("cases.json", 40, 5), ("holdout.json", 8, 1)])
def test_quality_cases_have_fixed_evidence_and_review_contract(filename, count, per_group):
    path = ROOT / filename
    assert path.exists(), "구현 전에 고정할 합성 평가 자료가 필요하다"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == count
    assert len({case["id"] for case in cases}) == count
    assert Counter(case["group"] for case in cases) == Counter({group: per_group for group in GROUPS})
    for case in cases:
        assert set(case) >= {"id", "group", "gate", "now", "seed_state", "sessions", "query", "review_actions", "expected"}
        assert case["gate"] in {"required", "regression", "observe"}
        assert case["query"] and case["now"]
        expected = case["expected"]
        assert set(expected) >= {"memory_ids", "fact_ids", "turn_ids", "allowed_claims", "forbidden_claims", "forbidden_changes", "corrections"}
        memories = case["seed_state"]["memories"]
        facts = case["seed_state"]["facts"]
        turns = [turn for memory in memories for turn in memory["messages"]]
        turns += [turn for session in case["sessions"] for turn in session["messages"]]
        for key, objects in [("memory_ids", memories), ("fact_ids", facts), ("turn_ids", turns)]:
            assert set(expected[key]) <= {obj["id"] for obj in objects}
        assert expected["allowed_claims"] or expected["forbidden_claims"]
        assert case["review_actions"]
        assert all(action["action"] in {"approve", "reject", "correct_subject", "edit_target", "delete_target"} for action in case["review_actions"])
        if case["group"] == "temporal":
            assert case["gate"] == "observe"
