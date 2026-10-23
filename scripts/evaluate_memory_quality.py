"""합성 기억 평가 명령줄. 종료 코드: 0 완료, 2 실행 오류, 3 근거 누락/예산 소진."""

import argparse
import asyncio
import json
from pathlib import Path

from .memory_quality_eval import ApiBudget, evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=["mock", "live"])
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--group", choices=["profile", "followup", "temporal", "raw_detail", "assertion", "abstention", "multi_memory", "boundary", "experience"])
    parser.add_argument("--experience-mode", choices=["enabled", "disabled"])
    parser.add_argument("--repeat-critical", type=int, default=1)
    parser.add_argument("--cache-embeddings", action="store_true", help="동일 실행의 동일 입력 임베딩 재사용; 요약·답변은 매번 새로 생성")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--embedding-provider")
    parser.add_argument("--embedding-model")
    parser.add_argument("--max-api-requests", type=int)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--response-tokens", type=int, default=1024)
    parser.add_argument("--summary-tokens", type=int, default=2048)
    args = parser.parse_args()
    if args.mode == "live":
        for name in ("provider", "model", "embedding_provider", "embedding_model", "max_api_requests"):
            if not getattr(args, name):
                parser.error(f"live 평가에는 {name} 설정이 필요합니다")
    if args.repeat_critical < 1:
        parser.error("반복 횟수는 양수여야 합니다")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = [case for case in cases if not args.group or case["group"] == args.group]
    cases = [case for case in cases for _ in range(args.repeat_critical if (bool(case.get("followups")) if case["group"] == "experience" else case["gate"] != "observe") else 1)]
    config = {name: getattr(args, name) for name in ("provider", "model", "embedding_provider", "embedding_model", "max_api_requests", "response_tokens", "summary_tokens", "cache_embeddings", "experience_mode") if getattr(args, name) is not None}
    budget = ApiBudget(args.max_api_requests or 1, args.ledger)
    try:
        result = asyncio.run(evaluate(cases, mode=args.mode, config=config, budget=budget))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "api_requests": budget.total, "calls_by_model": budget.by_model}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = sum(any(case["missing_evidence"].values()) for case in result["cases"])
    forbidden = sum(bool(case["state_grade"]["forbidden_changes"]) for case in result["cases"])
    corrections = sum(any(item["status"] in {"missing_target", "incorrect_state", "not_applied"}
                          for item in case["state_grade"]["corrections"]) for case in result["cases"]) if args.mode == "live" else 0
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "missing_evidence_cases": missing,
                      "forbidden_change_cases": forbidden, "failed_correction_cases": corrections,
                      "api_requests": budget.total, "calls_by_model": budget.by_model}))
    return 3 if missing or forbidden or corrections or result["status"] != "complete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
