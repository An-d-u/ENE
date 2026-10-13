"""평가 실행기의 격리·예산·근거 추적 계약."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_mock_evaluation_is_isolated_and_keeps_answers_ungraded(tmp_path, monkeypatch):
    from scripts.memory_quality_eval import evaluate

    sentinel = tmp_path / "real"
    sentinel.mkdir()
    (sentinel / "memory.json").write_text("접근 금지", encoding="utf-8")
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(sentinel))
    cases = json.loads((Path(__file__).parent / "fixtures/memory_quality/cases.json").read_text(encoding="utf-8"))
    result = asyncio.run(evaluate(cases[:1], mode="mock"))
    assert os.environ["ENE_USER_DATA_DIR"] == str(sentinel)
    assert (sentinel / "memory.json").read_text(encoding="utf-8") == "접근 금지"
    assert result["api_requests"] == 0
    assert result["cases"][0]["answer_grade"] == "ungraded"
    assert result["cases"][0]["trace"]["fact_ids"]
    assert result["cases"][0]["missing_evidence"]["fact_ids"] == []
    assert result["mode"] == "mock"


def test_budget_counts_actual_attempts_and_refuses_before_request():
    from scripts.memory_quality_eval import ApiBudget, BudgetExceeded

    budget = ApiBudget(2)
    budget.reserve("sample-model", "summary")
    budget.reserve("sample-model", "response")
    with pytest.raises(BudgetExceeded):
        budget.reserve("embedding-model", "embedding")
    assert budget.total == 2
    assert budget.by_model == {"sample-model": 2}


def test_budget_applies_at_transport_boundary_including_repeated_attempts():
    import httpx
    from scripts.memory_quality_eval import ApiBudget, BudgetExceeded, request_boundary

    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(503, request=request)
    budget = ApiBudget(2)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client, request_boundary("live", budget):
        for _ in range(2):
            client.post("https://example.invalid/v1beta/models/synthetic-model:generateContent", json={})
        with pytest.raises(BudgetExceeded):
            client.post("https://example.invalid/v1beta/models/synthetic-model:generateContent", json={})
    assert len(sent) == 2
    assert budget.by_model == {"synthetic-model": 2}


def test_default_prompt_paths_are_rebound_even_after_prior_import(tmp_path):
    from src.ai import prompt_config
    from scripts.memory_quality_eval import isolated_storage

    previous = prompt_config.BASE_SYSTEM_PROMPT_PATH
    with isolated_storage() as root:
        assert prompt_config.BASE_SYSTEM_PROMPT_PATH.is_relative_to(root)
        assert prompt_config.BASE_SYSTEM_PROMPT_PATH.exists()
    assert prompt_config.BASE_SYSTEM_PROMPT_PATH == previous


def test_trace_does_not_change_context_or_contain_raw_text(tmp_path):
    from src.ai.memory import MemoryManager
    from src.ai.memory_context_builder import build_memory_context
    from src.ai.memory_types import MemoryContextTrace, MemoryEntry

    manager = MemoryManager(str(tmp_path / "memory.json"))
    manager.memories = [MemoryEntry("m1", "합성 종이 다리는 붉다.", [], "2025-01-02", entity_names=["종이 다리"])]
    client = SimpleNamespace(memory_manager=manager, settings=SimpleNamespace(config={}), _prompt_language=lambda: "ko")
    trace = MemoryContextTrace()
    plain = asyncio.run(build_memory_context(client, "종이 다리"))
    traced = asyncio.run(build_memory_context(client, "종이 다리", trace=trace))
    assert plain == traced
    assert "m1" in trace.summary_ids
    assert "합성" not in json.dumps(trace.to_dict(), ensure_ascii=False)


def test_review_actions_bind_server_proposals_and_report_missing(tmp_path):
    from scripts.memory_quality_eval import prepare_review_actions
    from src.ai.profile_review import make_proposals
    from src.ai.user_profile import UserProfile, ProfileFact
    profile = UserProfile(tmp_path / "profile.json")
    profile.facts = [ProfileFact("유리 돛은 미완성이다.", "goal", "2025-01-01", id="f", subject="유리 돛")]
    update = dict(category="goal", content="유리 돛을 투명 돛으로 부른다.", subject="유리 돛",
                  state="active", assertion="current", evidence="유리 돛의 이름을 바꾼다.", replaces="f")
    pending = dict(review_id="review", summary="합성 요약", user_facts=[], ene_facts=[],
                   topic_hints=[], memory_meta={"profile_updates": [update]},
                   profile_proposals=make_proposals(profile.facts, [update]))
    action = dict(action="correct_subject", target_id="f", subject="유리 돛",
                  evidence=update["evidence"], corrected_subject="투명 돛")
    payload, outcomes = prepare_review_actions(pending, profile, [action])
    row = payload["profile_selections"][0]
    assert row["proposal_id"] == pending["profile_proposals"][0].proposal_id
    assert row["edits"]["subject"] == "투명 돛" and row["confirm_subject"]
    assert outcomes[0]["status"] == "applied"
    _, missing = prepare_review_actions(pending, profile, [dict(action, evidence="다른 합성 근거")])
    assert missing[0]["status"] == "missing_proposal"
    unbound = dict(update, category="preference", replaces="")
    pending["profile_proposals"] = make_proposals(profile.facts, [unbound])
    _, missing = prepare_review_actions(pending, profile, [action])
    assert missing[0]["status"] == "missing_target_binding"


def test_state_grading_detects_overwrite_and_preserves_external_delete():
    from scripts.memory_quality_eval import grade_state
    expected = {"forbidden_changes": [{"fact_id": "f"}], "corrections": []}
    before = [{"id": "f", "content": "기존 합성 상태"}]
    assert grade_state(expected, before, [{"id": "f", "content": "덮어쓴 상태"}])["forbidden_changes"] == ["f"]
    assert grade_state(expected, [], [])["forbidden_changes"] == []
    assert grade_state(expected, [], before)["forbidden_changes"] == ["f"]


def test_state_grading_fails_unchanged_correction_even_when_answer_is_right():
    from scripts.memory_quality_eval import grade_state
    before = [{"id": "f", "content": "기존 합성 상태", "subject": "투명 판"}]
    expected = {"forbidden_changes": [], "corrections": [{"fact_id": "f", "content": "바뀐 합성 상태"}]}
    assert grade_state(expected, before, before)["corrections"][0]["status"] == "not_applied"
    expected["corrections"] = [{"fact_id": "f", "subject": "유리 판"}]
    assert grade_state(expected, before, before)["corrections"][0]["status"] == "incorrect_state"


def test_evaluator_composition_matches_public_gemini_memory_path(tmp_path, monkeypatch):
    from scripts.memory_quality_eval import isolated_storage, _evaluation_settings, compose_evaluation_message
    from src.ai.llm_provider import create_llm_client, LLMProviderConfig
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry
    from src.ai.memory_context_builder import build_memory_context
    with isolated_storage():
        manager = MemoryManager(tmp_path / "memory.json")
        manager.memories = [MemoryEntry("sail", "종이 돛은 파랗다.", [], "2025-01-01", entity_names=["종이 돛"])]
        client = create_llm_client(LLMProviderConfig(provider="gemini", api_key="synthetic", model_name="synthetic"),
                                   settings=_evaluation_settings(), memory_manager=manager)
        sent = []
        monkeypatch.setattr(client, "send_message", lambda message, **kwargs: sent.append((message, kwargs)))
        query = "종이 돛은 무슨 색이야?"
        expected = compose_evaluation_message(query, asyncio.run(build_memory_context(client, query)), client.settings)
        asyncio.run(client.send_message_with_memory(query))
        assert sent[0][0] == expected
        assert sent[0][1]["history_user_content"] == query
