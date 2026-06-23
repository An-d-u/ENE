import json

from src.ai.memory import MemoryManager
from src.ai.memory_types import create_memory_entry


def test_load_reads_existing_utf8_bom_memory_file(tmp_path):
    memory_file = tmp_path / "memory.json"
    memory = create_memory_entry("기존 BOM 기억", ["안전한 예시 문장"])
    payload = {"memories": [memory.to_dict()], "last_updated": "2026-06-23T10:00:00"}
    memory_file.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8-sig"))

    manager = MemoryManager(str(memory_file))

    assert len(manager.memories) == 1
    assert manager.memories[0].summary == "기존 BOM 기억"
