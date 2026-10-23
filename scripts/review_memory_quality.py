"""합성 실제 모델 보고서에 검토자의 답변·저장 상태 판정을 연결한다."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


def report_hash(report):
    return sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _reports(report):
    return report if isinstance(report, list) else [report]


def make_template(report):
    cases = [case for item in _reports(report) for case in item["cases"]]
    return {
        "report_hash": report_hash(report), "reviewer": {"kind": "", "name": ""},
        "cases": [{"index": index, "id": case["id"], "answer": "ungraded",
                   "state": "ungraded", "reason": ""} for index, case in enumerate(cases)],
    }


def assess(report, review, required_repetitions):
    """의미 검토는 기계적 실패를 덮어쓰지 않으며 에이전트와 사람 승인을 구분한다."""
    items = _reports(report)
    cases = [case for item in items for case in item["cases"]]
    reviewer = review.get("reviewer", {})
    result = {"status": "pending", "report_hash": report_hash(report), "reviewer": reviewer,
              "human_approved": False, "failures": [], "pending": [], "observations": []}
    rows = review.get("cases", [])
    valid_statuses = {"pass", "fail", "ungraded"}
    if len({report_hash(item) for item in items}) != len(items):
        return dict(result, status="invalid", failures=["동일 보고서를 반복 실험으로 중복 집계할 수 없다."])
    conditions = {}
    for item in items:
        config = item.get("config", {})
        condition = {key: item.get(key) for key in ("prompt_hash", "prompt_hashes", "settings_hash")}
        condition["models"] = {key: config.get(key) for key in (
            "provider", "model", "embedding_provider", "embedding_model", "response_tokens", "summary_tokens")}
        for case in item["cases"]:
            conditions.setdefault(case["id"], set()).add(report_hash(condition))
    if any(len(values) > 1 for values in conditions.values()):
        return dict(result, status="invalid", failures=["같은 사례의 모델·프롬프트·설정이 서로 달라 반복 결과를 합산할 수 없다."])
    if (review.get("report_hash") != result["report_hash"] or len(rows) != len(cases)
            or {row.get("index") for row in rows} != set(range(len(cases)))
            or any(row.get("answer") not in valid_statuses or row.get("state") not in valid_statuses for row in rows)):
        return dict(result, status="invalid", failures=["보고서 해시 또는 검토 행이 일치하지 않는다."])
    rows = {row["index"]: row for row in rows}
    if any(rows[index].get("id") != case["id"] for index, case in enumerate(cases)):
        return dict(result, status="invalid", failures=["검토 행의 사례 ID가 일치하지 않는다."])
    if reviewer.get("kind") not in {"human", "agent"} or not reviewer.get("name"):
        result["pending"].append("검토자의 종류와 이름이 필요하다.")
    if any(item.get("mode") != "live" or item.get("status") != "complete" for item in items):
        result["pending"].append("실제 모델 평가가 완료되지 않았다.")
    if not required_repetitions or any(not isinstance(count, int) or isinstance(count, bool) or count < 1 for count in required_repetitions.values()):
        return dict(result, status="invalid", failures=["필수 사례별 반복 횟수가 필요하다."])
    counts = Counter(case["id"] for case in cases)
    result["case_counts"] = dict(counts)
    for identity, required in required_repetitions.items():
        if counts[identity] < required:
            result["pending"].append(f"{identity}: {counts[identity]}/{required}회")
    for index, case in enumerate(cases):
        row = rows[index]
        issues = []
        if any(case["missing_evidence"].values()):
            issues.append("필수 근거 누락")
        grade = case["state_grade"]
        if grade["forbidden_changes"]:
            issues.append("금지 상태 변경")
        if any(item["status"] in {"missing_target", "incorrect_state", "not_applied"} for item in grade["corrections"]):
            issues.append("정정 미반영")
        # 사전 정의된 외부 수정·삭제로 인한 재검토 요구는 정상 차단이다.
        expected_refresh = any(action.get("action") in {"edit_target", "delete_target"} and action.get("status") == "applied"
                               for action in case.get("review_actions", []))
        if any(item.get("status") == "failed" and not (expected_refresh and item.get("error") == "StaleProfileReview") for item in case["storage"]):
            issues.append("저장 실패")
        if "fail" in (row["answer"], row["state"]):
            issues.append("검토자 불합격")
        destination = "observations" if case["gate"] == "observe" else "failures"
        if issues:
            result[destination].append({"index": index, "id": case["id"], "issues": issues, "reason": row.get("reason", "")})
        if "ungraded" in (row["answer"], row["state"]) or not row.get("reason", "").strip():
            result["pending"].append(f"{index}/{case['id']}: 의미 검토와 판정 근거가 필요하다.")
    result["status"] = "fail" if result["failures"] else "pending" if result["pending"] else "pass"
    result["human_approved"] = result["status"] == "pass" and reviewer.get("kind") == "human"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, help="사례 ID를 필수 실행 횟수에 연결한 JSON")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--create-template", action="store_true")
    parser.add_argument("--suite", choices=["memory", "experience"], default="memory")
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--baseline-review", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    from .experience_quality_review import make_experience_template, assess_experience
    if args.create_template:
        template = make_experience_template(report) if args.suite == "experience" else make_template(report)
        args.review.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    if args.manifest is None or args.output is None:
        parser.error("판정에는 --manifest와 --output이 필요합니다")
    review = json.loads(args.review.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.suite == "experience":
        baseline = json.loads(args.baseline_report.read_text(encoding="utf-8")) if args.baseline_report else None
        baseline_review = json.loads(args.baseline_review.read_text(encoding="utf-8")) if args.baseline_review else None
        result = assess_experience(report, review, manifest, baseline, baseline_review)
    else:
        result = assess(report, review, manifest)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "human_approved": result["human_approved"]}))
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
