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
