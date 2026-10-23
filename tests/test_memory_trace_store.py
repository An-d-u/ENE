"""로컬 진단은 대화 내용을 저장하지 않고 크기와 쓰기 경계를 지킨다."""
from concurrent.futures import ThreadPoolExecutor
import json

from src.ai.memory_types import MemoryContextTrace


def test_trace_store_whitelists_metadata_and_deduplicates_requests(tmp_path):
    from src.ai.memory_trace_store import save_retrieval_trace
    path = tmp_path / "memory_retrieval_trace.jsonl"
    trace = MemoryContextTrace(summary_ids=["m1"], experience_chars=40)
    trace.query = "저장하면 안 되는 합성 원문"
    trace.answer = "저장하면 안 되는 합성 답변"
    for _ in range(2):
        assert save_retrieval_trace(path, "request-one", trace)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["summary_ids"] == ["m1"]
    assert "원문" not in path.read_text(encoding="utf-8")
    assert "answer" not in rows[0] and "query" not in rows[0]


def test_trace_is_bounded_and_concurrent_writes_are_valid(tmp_path):
    from src.ai.memory_trace_store import save_retrieval_trace
    path = tmp_path / "memory_retrieval_trace.jsonl"
    trace = MemoryContextTrace()
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: save_retrieval_trace(path, f"request-{i}", trace, max_rows=10, max_bytes=3000), range(35)))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert 1 <= len(rows) <= 10
    assert path.stat().st_size <= 3000


def test_store_failure_does_not_raise(tmp_path, monkeypatch):
    from src.ai import memory_trace_store
    monkeypatch.setattr(memory_trace_store, "write_bytes_data_atomic", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    assert memory_trace_store.save_retrieval_trace(tmp_path / "trace.jsonl", "request", MemoryContextTrace()) is False


def test_context_records_only_when_feature_enabled(tmp_path):
    import asyncio
    from src.ai.memory_context_builder import build_memory_context
    from tests.test_experience_memory_context import client_for
    client = client_for(tmp_path, enabled=False)
    asyncio.run(build_memory_context(client, "나무 모빌 균형", memory_request_id="one"))
    path = tmp_path / "memory_retrieval_trace.jsonl"
    assert not path.exists()
    client.settings.config["experience_memory_enabled"] = True
    asyncio.run(build_memory_context(client, "나무 모빌 균형", memory_request_id="two"))
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["request_id"] == "two"
    assert row["experience_refs"][0]["memory_id"] == "past"
