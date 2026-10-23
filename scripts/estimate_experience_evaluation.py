"""동일 임베딩 캐시를 공유하는 기준선·후보 평가의 호출량을 외부 요청 없이 산출한다."""
import argparse
import asyncio
import json
from pathlib import Path

from scripts.memory_quality_eval import evaluate, ApiBudget


async def estimate(output):
    fixtures = Path(__file__).resolve().parents[1] / "tests/fixtures/conversation_experience"
    cases = sum([json.loads((fixtures / name).read_text(encoding="utf-8")) for name in ("cases.json", "holdout.json")], [])
    budget, cache = ApiBudget(1), {}
    output.mkdir(parents=True, exist_ok=True)
    result = {"api_requests": 0, "modes": {}}
    for mode in ("disabled", "enabled"):
        selected = cases if mode == "disabled" else cases + [case for case in cases if case.get("followups") for _ in range(2)]
        report = await evaluate(selected, mode="mock", config={"experience_mode": mode, "cache_embeddings": True},
                                budget=budget, embedding_cache=cache)
        (output / f"{mode}-mock.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        result["modes"][mode] = {
            "case_runs": len(report["cases"]),
            "response_calls": sum(len(case["turns"]) for case in report["cases"]),
            "summary_calls": sum(bool(session.get("summarize")) for case in selected for session in case["sessions"]),
            "embedding_logical_calls": sum(case["embedding_usage"]["logical_calls"] for case in report["cases"]),
            "embedding_inputs": sum(case["embedding_usage"]["inputs"] for case in report["cases"]),
            "embedding_cache_hits": sum(case["embedding_cache_hits"] for case in report["cases"]),
            "missing_evidence_runs": sum(any(case["missing_evidence"].values()) for case in report["cases"]),
        }
    result["estimated_calls_without_retries"] = sum(row["response_calls"] + row["summary_calls"] + row["embedding_logical_calls"] for row in result["modes"].values())
    result["limitations"] = "대역과 실제 의미 검색의 후보가 다르면 임베딩 수가 변한다. SDK 재시도·기존 평가 회귀는 별도 여유가 필요하다. 응답은 재사용하지 않는다."
    (output / "estimate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(estimate(args.output_dir)), ensure_ascii=False))


if __name__ == "__main__":
    main()
