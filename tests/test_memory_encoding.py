import json
from pathlib import Path

import pytest

from src.ai.memory import MemoryManager
from src.ai.memory_types import create_memory_entry
from src.ai.mood_manager import MoodManager
from src.core import app_paths


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


def test_read_bytes_data_returns_visible_raw_and_mirrors_runtime(tmp_path, monkeypatch):
    runtime_file = tmp_path / "mood_state.json"
    visible_file = tmp_path / "visible" / "mood_state.json"
    visible_raw = b"\xef\xbb\xbf{\n  \"version\": 2\n}"
    runtime_file.write_bytes(b'{"version":2}')
    monkeypatch.setattr(app_paths, "_get_visible_store_python_path", lambda *_args, **_kwargs: visible_file)
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: visible_raw)

    result = app_paths.read_bytes_data(runtime_file)

    assert result == visible_raw
    assert runtime_file.read_bytes() == visible_raw


def test_write_bytes_data_atomic_rejects_text_and_propagates_write_failure(tmp_path, monkeypatch):
    target = tmp_path / "state.bin"
    with pytest.raises(TypeError):
        app_paths.write_bytes_data_atomic(target, "not-bytes")
    monkeypatch.setattr(
        app_paths,
        "_write_file_bytes_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write denied")),
    )

    with pytest.raises(OSError, match="write denied"):
        app_paths.write_bytes_data_atomic(target, b"payload")


def test_read_bytes_data_propagates_authoritative_read_failure(tmp_path, monkeypatch):
    target = tmp_path / "state.bin"
    visible = tmp_path / "visible.bin"
    monkeypatch.setattr(app_paths, "_get_visible_store_python_path", lambda *_args, **_kwargs: visible)
    monkeypatch.setattr(
        app_paths,
        "_read_file_bytes_via_powershell",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read denied")),
    )

    with pytest.raises(OSError, match="read denied"):
        app_paths.read_bytes_data(target)


def test_mood_store_load_uses_visible_raw_when_runtime_is_semantically_same(tmp_path, monkeypatch):
    runtime_file = tmp_path / "mood_state.json"
    visible = {
        "version": 2,
        "profile": "affectionate",
        "axes": {"valence": 0.3, "energy": 0.1, "bond": 0.6, "stress": -0.2},
        "updated_at": "2026-08-15T03:00:00+00:00",
    }
    runtime_file.write_text(json.dumps(visible, separators=(",", ":")), encoding="utf-8")
    visible_raw = json.dumps(visible, ensure_ascii=False, indent=2).encode("utf-8-sig")
    save_calls = []
    backup_calls = []

    def fake_store_read(path, **_kwargs):
        if Path(path) != runtime_file:
            raise FileNotFoundError
        return visible_raw

    def fake_raw_write(path, payload, **_kwargs):
        backup_calls.append((Path(path), payload))
        Path(path).write_bytes(payload)
        return Path(path)

    def fake_store_save(path, payload, **kwargs):
        assert Path(path) == runtime_file
        save_calls.append((payload, kwargs))
        runtime_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return runtime_file

    monkeypatch.setattr("src.ai.mood_manager.app_paths.read_bytes_data", fake_store_read)
    monkeypatch.setattr("src.ai.mood_manager.app_paths.write_bytes_data_atomic", fake_raw_write)
    monkeypatch.setattr("src.ai.mood_manager.app_paths.save_json_data", fake_store_save)

    manager = MoodManager(state_file=runtime_file)

    assert manager.state["relationship"] == {"affection": 0.6, "trust": 0.0}
    assert backup_calls == [(tmp_path / "mood_state.json.v2.bak", visible_raw)]
    assert len(save_calls) == 1
    assert save_calls[0][0]["version"] == 3
    assert save_calls[0][1] == {
        "encoding": "utf-8",
        "indent": 2,
        "ensure_ascii": False,
        "trailing_newline": True,
    }


def test_mood_store_existing_visible_v2_backup_is_not_replaced(tmp_path, monkeypatch):
    runtime_file = tmp_path / "mood_state.json"
    visible = {
        "version": 2,
        "profile": "calm",
        "axes": {"valence": 0.0, "energy": 0.0, "bond": 0.0, "stress": 0.0},
        "updated_at": "2026-08-15T03:00:00+00:00",
    }
    visible_raw = json.dumps(visible).encode("utf-8-sig")
    writes = []

    def fake_read(path, **_kwargs):
        if Path(path).name.endswith(".v2.bak"):
            return b"first-visible-backup"
        return visible_raw

    monkeypatch.setattr("src.ai.mood_manager.app_paths.read_bytes_data", fake_read)
    monkeypatch.setattr(
        "src.ai.mood_manager.app_paths.write_bytes_data_atomic",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    monkeypatch.setattr("src.ai.mood_manager.app_paths.save_json_data", lambda *args, **kwargs: runtime_file)

    MoodManager(state_file=runtime_file)

    assert writes == []


def test_mood_store_corrupt_visible_raw_is_locked_without_rewrite(tmp_path, monkeypatch):
    runtime_file = tmp_path / "mood_state.json"
    runtime_file.write_bytes(b"stale-runtime")
    visible_raw = b"{corrupt-visible"
    monkeypatch.setattr("src.ai.mood_manager.app_paths.read_bytes_data", lambda *_args, **_kwargs: visible_raw)

    manager = MoodManager(state_file=runtime_file)

    assert manager.get_load_status() == {"error_code": "corrupt_state", "write_locked": True}
    assert runtime_file.read_bytes() == b"stale-runtime"


def test_mood_store_reset_refreshes_current_corrupt_authoritative_raw(tmp_path, monkeypatch):
    runtime_file = tmp_path / "mood_state.json"
    authoritative = {"raw": b"{first-corrupt"}

    backup_calls = []

    def fake_store_read(*_args, **_kwargs):
        return authoritative["raw"]

    def fake_raw_write(path, payload, **_kwargs):
        backup_calls.append((Path(path), payload))
        return Path(path)

    def fake_store_save(path, payload, **_kwargs):
        Path(path).write_text(json.dumps(payload), encoding="utf-8")
        return Path(path)

    monkeypatch.setattr("src.ai.mood_manager.app_paths.read_bytes_data", fake_store_read)
    monkeypatch.setattr("src.ai.mood_manager.app_paths.write_bytes_data_atomic", fake_raw_write)
    monkeypatch.setattr("src.ai.mood_manager.app_paths.save_json_data", fake_store_save)
    manager = MoodManager(state_file=runtime_file)
    authoritative["raw"] = b"{latest-corrupt"

    manager.reset_state()

    assert len(backup_calls) == 1
    assert backup_calls[0][0].name.startswith("mood_state.json.recovery.")
    assert backup_calls[0][1] == authoritative["raw"]
