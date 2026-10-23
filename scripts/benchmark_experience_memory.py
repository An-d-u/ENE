"""외부 호출 없이 1,000개 합성 기억의 로컬 검색 비용을 측정한다."""
import argparse
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace

from scripts.memory_quality_eval import SyntheticEmbedding, MeasuredEmbedding, ApiBudget, request_boundary
from src.ai.memory import MemoryManager
from src.ai.memory_context_builder import build_memory_context
from src.ai.memory_types import MemoryEntry, MemoryContextTrace


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction + .5))]


async def benchmark(count=1000, repeats=20):
    results = {}
    budget = ApiBudget(1)
    with TemporaryDirectory(prefix="ene-experience-benchmark-") as directory, request_boundary("mock", budget):
        for enabled in (False, True):
            generator = MeasuredEmbedding(SyntheticEmbedding(), budget)
            manager = MemoryManager(Path(directory) / str(enabled) / "memory.json", generator)
            for index in range(count):
                subject = "나무 모빌" if index % 50 == 0 else f"합성 장식 {index}"
                user = subject + "의 균형을 맞추고 있어." if index % 50 == 0 else subject + "의 색을 골랐어."
                summary = subject + ": " + user
                manager.memories.append(MemoryEntry(str(index), summary, [
                    {"role": "user", "text": user},
                    {"role": "assistant", "text": "작은 부분부터 살펴보자."},
                    {"role": "user", "text": "한 부분을 바꾸니 원하는 모양이 됐어."},
                ], "2025-01-02T12:00:00+09:00", embedding=await generator.embed(summary),
                    embedding_provider=generator.provider, embedding_model=generator.model))
            # 디스크 저장 시간은 검색 성능과 구분한다. 내용 없는 진단 파일 쓰기는 포함한다.
            manager.record_context_usage = lambda *args: []
            client = SimpleNamespace(memory_manager=manager, settings=SimpleNamespace(config={
                "experience_memory_enabled": enabled, "max_recent_memories": 0, "max_important_memories": 0,
            }))
            for cache_mode in ("cold", "warm"):
                rows = []
                for iteration in range(repeats):
                    if cache_mode == "cold":
                        manager._raw_chunk_embedding_cache.clear()
                    before = dict(generator.embedding_usage)
                    trace = MemoryContextTrace()
                    started = perf_counter()
                    context = await build_memory_context(client, "나무 모빌 균형을 맞추고 싶어", trace=trace,
                                                         memory_request_id=f"{enabled}:{cache_mode}:{iteration}")
                    rows.append({"ms": (perf_counter() - started) * 1000, "chars": len(context),
                        "embedding_inputs": generator.embedding_usage["inputs"] - before["inputs"],
                        "logical_calls": generator.embedding_usage["logical_calls"] - before["logical_calls"],
                        "experience_candidates": len(trace.candidates.get("experience_memories", []))})
                times = [row["ms"] for row in rows]
                results[f"{'enabled' if enabled else 'disabled'}_{cache_mode}"] = {
                    "p50_ms": round(median(times), 3), "p95_ms": round(percentile(times, .95), 3),
                    "context_chars": rows[-1]["chars"], "token_count": "unknown_without_live_provider",
                    "embedding_inputs": sorted({row["embedding_inputs"] for row in rows}),
                    "logical_calls": sorted({row["logical_calls"] for row in rows}),
                    "experience_candidates": rows[-1]["experience_candidates"],
                }
    for cache_mode in ("cold", "warm"):
        results[f"extra_{cache_mode}_p95_ms"] = round(results[f"enabled_{cache_mode}"]["p95_ms"] - results[f"disabled_{cache_mode}"]["p95_ms"], 3)
    return {"memories": count, "repeats": repeats, "api_requests": budget.total,
            "scope": "임베딩 대역 계산과 진단 쓰기 포함, 외부 모델·기억 사용 횟수 저장 제외", "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    with redirect_stdout(io.StringIO()):
        report = asyncio.run(benchmark(repeats=args.repeats))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
