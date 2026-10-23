"""경험 평가의 비율·중대 오류·반복·기준선 비교를 각각 판정한다."""
from collections import Counter

from .review_memory_quality import _reports, report_hash


DIMENSIONS = ("connection", "prior_response", "relevance", "restraint", "non_repetition", "grounding", "state")


def make_experience_template(report):
    cases = [case for item in _reports(report) for case in item["cases"]]
    return {"report_hash": report_hash(report), "reviewer": {"kind": "", "name": ""},
            "cases": [{"index": index, "id": case["id"], "reason": "",
                       "turns": [{"index": turn_index, "reason": "", **{key: "ungraded" for key in DIMENSIONS}}
                                 for turn_index in range(len(case.get("turns", [])))],
                       **{key: "ungraded" for key in DIMENSIONS}} for index, case in enumerate(cases)]}


def _condition(report):
    config = report.get("config", {})
    return {"code_commit": report.get("code_commit"), "prompts": report.get("prompt_hashes"),
            "settings": {k: v for k, v in report.get("settings", {}).items() if k != "experience_memory_enabled"},
            "models": {k: config.get(k) for k in ("provider", "model", "embedding_provider", "embedding_model", "response_tokens", "summary_tokens")}}


def _collect(report, review, manifest, *, baseline=False):
    result = {"invalid": [], "pending": [], "hard_failures": [], "observations": [], "first": {}, "conditions": []}
    reports = _reports(report)
    if not reports or len({report_hash(item) for item in reports}) != len(reports):
        result["invalid"].append("중복 또는 빈 보고서")
        return result
    cases = [case for item in reports for case in item.get("cases", [])]
    rows = review.get("cases", [])
    if (review.get("report_hash") != report_hash(report) or len(rows) != len(cases)
            or {row.get("index") for row in rows} != set(range(len(cases)))):
        result["invalid"].append("검토 해시 또는 행 불일치")
        return result
    by_index = {row["index"]: row for row in rows}
    counts = Counter(case["id"] for case in cases)
    expected = manifest["repetitions"]
    if set(counts) - set(expected):
        result["invalid"].append("명세에 없는 평가 사례")
    for identity, required in expected.items():
        if counts[identity] < (1 if baseline else required):
            result["pending"].append(f"반복 부족: {identity}")
    reviewer = review.get("reviewer", {})
    if reviewer.get("kind") not in {"agent", "human"} or not reviewer.get("name"):
        result["pending"].append("검토자 미지정")
    fixture_conditions = {}
    for item in reports:
        condition = _condition(item)
        result["conditions"].append(condition)
        if item.get("mode") != "live" or item.get("status") != "complete":
            result["pending"].append("실제 모델 실행 미완료")
        enabled = item.get("settings", {}).get("experience_memory_enabled")
        if enabled is not (not baseline):
            result["invalid"].append("후보 또는 기준선 기능 설정 불일치")
        for case in item.get("cases", []):
            fixture_conditions.setdefault(case["id"], set()).add((case.get("fixture_case_hash"), case.get("evaluation_now")))
    if len({report_hash(value) for value in result["conditions"]}) > 1 or any(len(values) > 1 for values in fixture_conditions.values()):
        result["invalid"].append("서로 다른 코드·모델·설정·자료·시각을 반복으로 합산할 수 없다")
    result["fixture_conditions"] = fixture_conditions
    for index, case in enumerate(cases):
        row = by_index[index]
        identity = case["id"]
        if row.get("id") != identity or any(row.get(key) not in {"pass", "fail", "ungraded"} for key in DIMENSIONS):
            result["invalid"].append(f"검토 계약 불일치: {index}")
            continue
        if any(row[key] == "ungraded" for key in DIMENSIONS) or not row.get("reason", "").strip():
            result["pending"].append(f"미판정: {index}")
        turn_reviews = row.get("turns", [])
        if (len(turn_reviews) != len(case.get("turns", [])) or not turn_reviews
                or {turn.get("index") for turn in turn_reviews} != set(range(len(turn_reviews)))):
            result["pending"].append(f"턴별 검토 누락: {index}")
        for turn in turn_reviews:
            if any(turn.get(key) not in {"pass", "fail", "ungraded"} for key in DIMENSIONS):
                result["invalid"].append(f"턴별 검토 계약 불일치: {index}")
            if any(turn.get(key) == "ungraded" for key in DIMENSIONS) or not turn.get("reason", "").strip():
                result["pending"].append(f"턴별 미판정: {index}/{turn.get('index')}")
        grades = [row, *turn_reviews]
        has_failure = any(value.get(key) == "fail" for value in grades for key in DIMENSIONS)
        policy = manifest["policies"].get(identity)
        family = manifest["families"].get(identity)
        if case.get("experience") != {"policy": policy, "family": family}:
            result["invalid"].append(f"사례 분류 불일치: {identity}")
        missing = any(case.get("missing_evidence", {}).values())
        safe = all(row[key] == "pass" for key in ("grounding", "state"))
        state = case.get("state_grade", {})
        storage_error = any(value.get("status") == "failed" for value in case.get("storage", []))
        if any(value.get(key) == "fail" for value in grades for key in ("grounding", "state")) or state.get("forbidden_changes") or storage_error:
            result["hard_failures"].append(f"중대한 오류: {index}/{identity}")
        if any(value.get("status") in {"not_applied", "incorrect_state", "missing_target"} for value in state.get("corrections", [])):
            result["hard_failures"].append(f"정정 미반영: {index}/{identity}")
        # 회수와 실제 답변 활용은 독립 지표다. 검색 차이만으로 답변 개선을 주장하지 않는다.
        passed = safe and all(value.get(key) == "pass" for value in grades for key in DIMENSIONS)
        if policy == "avoid" and has_failure:
            result["hard_failures"].append(f"음성 사례 오류: {index}/{identity}")
        if expected.get(identity, 1) > 1 and not baseline:
            if len(case.get("turns", [])) < 2:
                result["pending"].append(f"다중 턴 누락: {identity}")
            if missing or has_failure:
                result["hard_failures"].append(f"핵심 반복 실패: {index}/{identity}")
        if missing or has_failure:
            result["observations"].append({"index": index, "id": identity, "missing_evidence": missing, "reason": row.get("reason")})
        result["first"].setdefault(identity, {"retrieved": not missing, "applied": passed, "family": family, "policy": policy})
    return result


def assess_experience(report, review, manifest, baseline_report=None, baseline_review=None):
    result = {"status": "pending", "enable_default": False, "human_approved": False,
              "failures": [], "pending": [], "observations": [], "metrics": {}}
    if (manifest.get("version") != 1 or not manifest.get("repetitions")
            or any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in manifest["repetitions"].values())
            or set(manifest.get("policies", {})) != set(manifest["repetitions"])
            or set(manifest.get("families", {})) != set(manifest["repetitions"])):
        return dict(result, status="invalid", failures=["경험 평가 manifest 불일치"])
    positive_ids = {key for key, value in manifest["policies"].items() if value == "required"}
    holdout_ids = manifest.get("holdout_ids", [])
    if (Counter(manifest["policies"].values()) != {"required": 32, "avoid": 16}
            or Counter(manifest["repetitions"].values()) != {1: 40, 3: 8}
            or sorted(Counter(manifest["families"][key] for key in positive_ids).values()) != [4] * 8
            or len(holdout_ids) != 16 or len(set(holdout_ids)) != 16
            or not set(holdout_ids) <= set(manifest["repetitions"])
            or len(positive_ids & set(holdout_ids)) != 8):
        return dict(result, status="invalid", failures=["고정된 사례 수·유형·반복·별도 확인 비율 불일치"])
    candidate = _collect(report, review, manifest)
    if candidate["invalid"]:
        return dict(result, status="invalid", failures=candidate["invalid"])
    result["pending"].extend(candidate["pending"])
    result["failures"].extend(candidate["hard_failures"])
    result["observations"] = candidate["observations"]
    positives = {key: item for key, item in candidate["first"].items() if item["policy"] == "required"}
    holdout = {key: value for key, value in positives.items() if key in manifest.get("holdout_ids", [])}
    metrics = {"retrieved": sum(item["retrieved"] for item in positives.values()),
               "applied": sum(item["applied"] for item in positives.values()),
               "holdout_retrieved": sum(item["retrieved"] for item in holdout.values()),
               "holdout_applied": sum(item["applied"] for item in holdout.values())}
    metrics["by_family"] = dict(Counter(item["family"] for item in positives.values() if item["applied"]))
    result["metrics"] = metrics
    if len(positives) == 32:
        if metrics["retrieved"] < 29 or metrics["applied"] < 28 or metrics["holdout_retrieved"] < 7 or metrics["holdout_applied"] < 7:
            result["failures"].append("고정 비율 기준 미달")
        if any(metrics["by_family"].get(family, 0) < 3 for family in {item["family"] for item in positives.values()}):
            result["failures"].append("유형별 3/4 기준 미달")
    else:
        result["pending"].append("긍정 32개 전체 결과 필요")
    if baseline_report is None or baseline_review is None:
        result["pending"].append("기준선 비교 미완료")
    else:
        baseline = _collect(baseline_report, baseline_review, manifest, baseline=True)
        if baseline["invalid"]:
            return dict(result, status="invalid", failures=baseline["invalid"])
        result["pending"].extend(baseline["pending"])
        comparable = ({report_hash(x) for x in candidate["conditions"]} == {report_hash(x) for x in baseline["conditions"]}
                      and candidate["fixture_conditions"] == baseline["fixture_conditions"])
        if not comparable:
            return dict(result, status="invalid", failures=["기준선과 후보의 자료·코드·모델·시각이 다르다"])
        metrics["baseline_applied"] = sum(item["applied"] for item in baseline["first"].values() if item["policy"] == "required")
        if metrics["applied"] <= metrics["baseline_applied"]:
            result["failures"].append("기준선 대비 활용 개선이 확인되지 않았다")
    result["status"] = "pending" if result["pending"] else "fail" if result["failures"] else "pass"
    result["enable_default"] = result["status"] == "pass"
    result["human_approved"] = result["status"] == "pass" and review.get("reviewer", {}).get("kind") == "human"
    return result
