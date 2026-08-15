import json

from src.ai.memory import MemoryManager
from src.ai.memory_types import create_memory_entry
from src.ai.mood_manager import MoodManager


def test_load_reads_existing_utf8_bom_memory_file(tmp_path):
    memory_file = tmp_path / "memory.json"
    memory = create_memory_entry("기존 BOM 기억", ["안전한 예시 문장"])
    payload = {"memories": [memory.to_dict()], "last_updated": "2026-06-23T10:00:00"}
    memory_file.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8-sig"))

    manager = MemoryManager(str(memory_file))

    assert len(manager.memories) == 1
    assert manager.memories[0].summary == "기존 BOM 기억"


def test_mood_v3_save_uses_utf8_without_bom(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = MoodManager(state_file=state_file)

    manager.reset_state()

    raw = state_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["version"] == 3
