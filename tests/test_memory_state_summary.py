import json
from types import SimpleNamespace

from src.ai.summary_parser import parse_summary_response_with_topic_memory
from src.ai.summary_prompt import build_summary_prompt
from src.ai.user_profile import ProfileFact


def test_profile_updates_parse_without_changing_summary_contract():
    updates = [{"category": "goal", "content": "모형 제작을 보류했다.", "state": "paused"}]
    text = "[SUMMARY]\n가상 대화 요약\n[MASTER_INFO]\n- [goal] 모형 제작을 보류했다.\n[ENE_INFO]\n- none\n[MEMORY_META]\n- confidence: 0.9\n[PROFILE_UPDATES]\n" + json.dumps(updates, ensure_ascii=False) + "\n[TOPIC_MEMORY]\n- none"
    summary, facts, _, meta, topics = parse_summary_response_with_topic_memory(text)
    assert summary == "가상 대화 요약"
    assert facts == ["[goal] 모형 제작을 보류했다."]
    assert meta["profile_updates"] == updates
    assert topics == []


def test_malformed_update_section_fails_closed():
    result = parse_summary_response_with_topic_memory("[SUMMARY]\n가상 요약\n[PROFILE_UPDATES]\n[{broken}")
    assert result[3]["profile_updates"] == []


def test_profile_snapshot_supplies_stable_ids_and_update_evidence_rules():
    fact = ProfileFact("모형 제작 계획", "goal", "2026-01-01")
    profile = SimpleNamespace(basic_info={}, preferences={}, get_all_facts=lambda: [fact])
    prompt = build_summary_prompt([("user", "가상 입력")], user_profile=profile).prompt
    assert fact.id in prompt
    assert "[PROFILE_UPDATES]" in prompt
    assert "evidence" in prompt
    assert "historical" in prompt
