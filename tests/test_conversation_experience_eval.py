"""실제 대화 흐름과 경험 평가의 독립 승인 기준."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from scripts.memory_quality_eval import evaluate


ROOT = Path(__file__).parent / "fixtures/conversation_experience"


def cases():
    return sum([json.loads((ROOT / name).read_text(encoding="utf-8")) for name in ("cases.json", "holdout.json")], [])


def test_mock_experience_run_reports_evidence_and_never_grades_answers():
    result = asyncio.run(evaluate(cases()[:1], mode="mock", config={"experience_mode": "enabled"}))
    row = result["cases"][0]
    assert result["api_requests"] == 0
    assert result["settings"]["experience_memory_enabled"] is True
    assert row["experience"]["policy"] == "required"
    assert row["answer_grade"] == "ungraded"
    assert row["evaluation_now"] == cases()[0]["now"]
    assert row["turns"][1]["previous_response_source"] == "mock"


def test_followup_context_uses_generated_response_not_expected_text(monkeypatch):
    from src.ai.llm_client import GeminiClient
    from src.ai.memory_context_builder import build_memory_context as original_builder
    import src.ai.memory_context_builder as builder_module
    observed = []
    async def capture(*args, **kwargs):
        observed.append(deepcopy(kwargs.get("recent_memory_messages", [])))
        return await original_builder(*args, **kwargs)
    monkeypatch.setattr(builder_module, "build_memory_context", capture)
    monkeypatch.setattr(GeminiClient, "send_message", lambda *args, **kwargs: ("생성한 합성 응답",))
    # 외부 SDK만 대역으로 바꾸고 실제 응답 전달 경로를 검사한다.
    from scripts.memory_quality_eval import evaluate as run, SyntheticEmbedding
    monkeypatch.setenv("ENE_EVAL_EMBEDDING_KEY", "synthetic-key")
    monkeypatch.setattr("src.ai.embedding.create_embedding_generator", lambda **kwargs: SyntheticEmbedding())
    result = asyncio.run(run(cases()[:1], mode="live", config={"experience_mode": "enabled", "embedding_provider": "mock", "embedding_model": "lexical-hash"}))
    assert observed[1][-1]["role"] == "assistant"
    assert observed[1][-1]["text"] == "생성한 합성 응답"
    assert result["cases"][0]["turns"][1]["previous_response_source"] == "generated"


def reviewed_report(mode="enabled", baseline=False):
    from scripts.experience_quality_review import make_experience_template
    manifest = json.loads((ROOT / "approval_manifest.json").read_text(encoding="utf-8"))
    rows = []
    for case in cases():
        for repeat in range(1 if baseline else manifest["repetitions"][case["id"]]):
            rows.append(dict(id=case["id"], run_index=len(rows), fixture_case_hash=case["id"], evaluation_now=case["now"],
                missing_evidence={"experience_refs": []}, experience={"policy": case["expected"]["connection_policy"], "family": case["family"]},
                state_grade={"forbidden_changes": [], "corrections": []}, storage=[], turns=[{}, {}] if case.get("followups") else [{}]))
    report = dict(mode="live", status="complete", code_commit="same", prompt_hashes={"base": "fixed"},
                  settings={"experience_memory_enabled": mode == "enabled"}, config={"experience_mode": mode,"model":"synthetic"}, cases=rows)
    review = make_experience_template(report)
    review["reviewer"] = {"kind": "agent", "name": "합성 검토자"}
    for row in review["cases"]:
        for value in [row, *row["turns"]]:
            for key in ("connection", "prior_response", "relevance", "restraint", "non_repetition", "grounding", "state"):
                value[key] = "pass"
            value["reason"] = "합성 계약 확인"
    return report, review, manifest


def test_experience_gate_separates_ratios_from_critical_errors_and_baseline():
    from scripts.experience_quality_review import assess_experience
    from scripts.review_memory_quality import report_hash
    report, review, manifest = reviewed_report()
    baseline, baseline_review, _ = reviewed_report(mode="disabled", baseline=True)
    for row in baseline_review["cases"][:8]:
        row["connection"] = "fail"
    # 고유 사례 3개의 회수 실패는 비율에 반영하고 숨기지 않는다.
    target_ids = {"experience-continuation-2", "experience-difficulty-2", "experience-success-2"}
    for row in report["cases"]:
        if row["id"] in target_ids:
            row["missing_evidence"]["experience_refs"] = ["missing"]
    review["report_hash"] = report_hash(report)
    result = assess_experience(report, review, manifest, baseline, baseline_review)
    assert result["status"] == "pass"
    assert result["metrics"]["retrieved"] == 29
    assert len(result["observations"]) == 3
    review["cases"][0]["grounding"] = "fail"
    assert assess_experience(report, review, manifest, baseline, baseline_review)["status"] == "fail"


def test_ungraded_missing_repetitions_or_missing_baseline_never_enable():
    from scripts.experience_quality_review import assess_experience, make_experience_template
    report, review, manifest = reviewed_report()
    assert assess_experience(report, make_experience_template(report), manifest)["status"] == "pending"
    result = assess_experience(report, review, manifest)
    assert result["status"] == "pending" and not result["enable_default"]


def test_incompatible_or_duplicate_reports_are_not_valid_repetitions():
    from scripts.experience_quality_review import assess_experience, make_experience_template
    report, _, manifest = reviewed_report()
    duplicated = [report, deepcopy(report)]
    assert assess_experience(duplicated, make_experience_template(duplicated), manifest)["status"] == "invalid"


def test_retrieval_improvement_alone_is_not_response_use_improvement():
    from scripts.experience_quality_review import assess_experience
    from scripts.review_memory_quality import report_hash
    report, review, manifest = reviewed_report()
    baseline, baseline_review, _ = reviewed_report(mode="disabled", baseline=True)
    baseline["cases"][0]["missing_evidence"]["experience_refs"] = ["missing"]
    baseline_review["report_hash"] = report_hash(baseline)
    result = assess_experience(report, review, manifest, baseline, baseline_review)
    assert result["status"] == "fail"
    assert result["metrics"]["applied"] == result["metrics"]["baseline_applied"] == 32


def test_followup_failure_and_missing_turn_review_cannot_enable():
    from scripts.experience_quality_review import assess_experience
    report, review, manifest = reviewed_report()
    baseline, baseline_review, _ = reviewed_report(mode="disabled", baseline=True)
    baseline_review["cases"][0]["connection"] = "fail"
    review["cases"][0]["turns"][1]["non_repetition"] = "fail"
    assert assess_experience(report, review, manifest, baseline, baseline_review)["status"] == "fail"
    review["cases"][0]["turns"] = []
    assert assess_experience(report, review, manifest, baseline, baseline_review)["status"] == "pending"
