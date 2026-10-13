"""답변 의미 검토가 실행 실패나 부족한 반복을 가리지 못하는지 확인한다."""

from copy import deepcopy

from scripts.review_memory_quality import assess, make_template, report_hash


def sample():
    report = dict(mode="live", status="complete", cases=[dict(
        id="synthetic-1", gate="required", missing_evidence={"fact_ids": []},
        state_grade={"forbidden_changes": [], "corrections": []}, storage=[],
        answer=["합성 블록은 두 개다."], final_facts=[], raw_summary_outputs=[],
    )])
    review = make_template(report)
    review["reviewer"] = {"kind": "agent", "name": "독립 검토자"}
    review["cases"][0].update(answer="pass", state="pass", reason="근거와 답변을 대조했다.")
    return report, review


def test_ungraded_or_incomplete_repetition_cannot_pass():
    report, review = sample()
    assert assess(report, make_template(report), {"synthetic-1": 1})["status"] == "pending"
    assert assess(report, review, {"synthetic-1": 3})["status"] == "pending"
    result = assess(report, review, {"synthetic-1": 1})
    assert result["status"] == "pass"
    assert result["reviewer"]["kind"] == "agent"
    assert result["human_approved"] is False


def test_hard_failure_cannot_be_overridden_by_semantic_reviewer():
    report, review = sample()
    report["cases"][0]["state_grade"]["corrections"] = [{"fact_id": "f", "status": "not_applied"}]
    review["report_hash"] = report_hash(report)
    assert assess(report, review, {"synthetic-1": 1})["status"] == "fail"


def test_changed_output_and_duplicate_review_rows_are_rejected():
    report, review = sample()
    changed = deepcopy(report)
    changed["cases"][0]["answer"] = ["근거 없는 다른 값"]
    assert assess(changed, review, {"synthetic-1": 1})["status"] == "invalid"
    review["cases"].append(deepcopy(review["cases"][0]))
    assert assess(report, review, {"synthetic-1": 1})["status"] == "invalid"


def test_budget_exhaustion_and_mock_never_approve_live_quality():
    for field, value in [("status", "budget_exhausted"), ("mode", "mock")]:
        report, review = sample()
        report[field] = value
        review["report_hash"] = report_hash(report)
        assert assess(report, review, {"synthetic-1": 1})["status"] != "pass"


def test_unexpected_stale_review_is_a_failure():
    report, review = sample()
    report["cases"][0]["storage"] = [{"status": "failed", "error": "StaleProfileReview"}]
    review["report_hash"] = report_hash(report)
    assert assess(report, review, {"synthetic-1": 1})["status"] == "fail"


def test_duplicate_report_cannot_satisfy_repeated_experiments():
    report, _ = sample()
    combined = [report, deepcopy(report), deepcopy(report)]
    review = make_template(combined)
    review["reviewer"] = {"kind": "agent", "name": "검토자"}
    for row in review["cases"]:
        row.update(answer="pass", state="pass", reason="합성 근거 일치")
    assert assess(combined, review, {"synthetic-1": 3})["status"] == "invalid"


def test_different_model_or_prompt_cannot_be_pooled_as_repetitions():
    report, _ = sample()
    report.update(prompt_hash="first", settings_hash="fixed", config={"model": "synthetic-a"})
    for field, value in [("prompt_hash", "second"), ("config", {"model": "synthetic-b"})]:
        changed = deepcopy(report)
        changed[field] = value
        combined = [report, changed]
        review = make_template(combined)
        review["reviewer"] = {"kind": "agent", "name": "검토자"}
        for row in review["cases"]:
            row.update(answer="pass", state="pass", reason="합성 근거 일치")
        assert assess(combined, review, {"synthetic-1": 2})["status"] == "invalid"
