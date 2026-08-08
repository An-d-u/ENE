import json
import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core import app_paths
from src.core.app_paths import save_json_data_atomic


def test_save_json_data_atomic_writes_utf8_without_bom(tmp_path):
    target = tmp_path / "state.json"
    save_json_data_atomic(target, {"text": "가상 기록"})

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["text"] == "가상 기록"


def test_save_json_data_atomic_keeps_previous_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("replace failed")))

    with pytest.raises(OSError):
        save_json_data_atomic(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_save_json_data_atomic_uses_same_directory_fsync_and_replace(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "state.json"
    real_replace = os.replace
    real_fsync = os.fsync
    real_os_open = os.open
    replacements: list[tuple[Path, Path]] = []
    fsync_calls: list[int] = []
    open_calls: list[tuple[Path, int, int]] = []

    def tracking_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def tracking_fsync(file_descriptor):
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    def tracking_os_open(path, flags, mode=0o777, *, dir_fd=None):
        open_calls.append((Path(path), flags, mode))
        if dir_fd is None:
            return real_os_open(path, flags, mode)
        return real_os_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "replace", tracking_replace)
    monkeypatch.setattr(os, "fsync", tracking_fsync)
    monkeypatch.setattr(os, "open", tracking_os_open)

    save_json_data_atomic(target, {"version": 2})

    assert fsync_calls
    assert len(open_calls) == 1
    _, open_flags, open_mode = open_calls[0]
    assert open_flags & os.O_CREAT
    assert open_flags & os.O_EXCL
    assert open_flags & os.O_WRONLY
    assert open_mode == 0o600
    assert len(replacements) == 1
    source, destination = replacements[0]
    assert source.parent == target.parent
    assert re.fullmatch(rf"\.{re.escape(target.name)}\.\d+\.[0-9a-f]{{32}}\.tmp", source.name)
    assert destination == target
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}


def test_save_json_data_atomic_cleans_recognized_orphan_temp_files(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    orphan = tmp_path / f".state.json.43210.{'0' * 32}.tmp"
    unrelated = tmp_path / "state.json.unrelated.tmp"
    orphan.write_bytes(b"partial")
    unrelated.write_bytes(b"keep")
    monkeypatch.setattr(app_paths, "_is_process_running", lambda process_id: False)

    save_json_data_atomic(target, {"version": 3})

    assert not orphan.exists()
    assert unrelated.read_bytes() == b"keep"
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 3}


def test_save_json_data_atomic_preserves_unrecognized_temp_files(tmp_path):
    target = tmp_path / "state.json"
    unrecognized = tmp_path / ".state.json.external-writer.tmp"
    unrecognized.write_bytes(b"in-progress")

    save_json_data_atomic(target, {"version": 4})

    assert unrecognized.read_bytes() == b"in-progress"


def test_save_json_data_public_api_keeps_runtime_when_store_visible_replace_fails(
    tmp_path,
    monkeypatch,
):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)

    def fail_visible_replace(path: Path, raw: bytes) -> None:
        raise OSError("synthetic visible replace failure")

    monkeypatch.setattr(app_paths, "_write_file_bytes_via_powershell", fail_visible_replace)

    with pytest.raises(OSError, match="synthetic visible replace failure"):
        app_paths.save_json_data(runtime_path, {"version": 2})

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}


def test_save_json_data_public_api_preserves_format_options_and_return_path(tmp_path):
    target = tmp_path / "state.json"

    saved_path = app_paths.save_json_data(
        target,
        {"text": "가상 값"},
        encoding="utf-8",
        indent=None,
        ensure_ascii=True,
        trailing_newline=True,
    )

    assert saved_path == target
    expected = json.dumps({"text": "가상 값"}, indent=None, ensure_ascii=True) + os.linesep
    assert target.read_bytes() == expected.encode("utf-8")


def _force_store_python_bridge(monkeypatch, runtime_root: Path, visible_root: Path) -> None:
    monkeypatch.delenv("ENE_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths, "is_windows_store_python_runtime", lambda: True)
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: runtime_root)
    monkeypatch.setattr(app_paths, "get_visible_user_data_dir", lambda app_name=app_paths.APP_NAME: visible_root)


def test_store_atomic_save_keeps_runtime_and_input_unchanged_when_visible_replace_fails(
    tmp_path,
    monkeypatch,
):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    visible_path = visible_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    payload = {"version": 2}
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)

    def fail_visible_replace(path: Path, raw: bytes) -> None:
        assert path == visible_path
        assert json.loads(raw.decode("utf-8")) == payload
        raise OSError("synthetic visible replace failure")

    monkeypatch.setattr(app_paths, "_write_file_bytes_via_powershell", fail_visible_replace)

    with pytest.raises(OSError, match="synthetic visible replace failure"):
        save_json_data_atomic(runtime_path, payload)

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}
    assert payload == {"version": 2}


def test_store_atomic_save_succeeds_when_runtime_cache_refresh_fails(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    visible_bytes: dict[str, bytes] = {}
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)

    def commit_visible(path: Path, raw: bytes) -> None:
        visible_bytes["payload"] = raw

    real_atomic_write = app_paths._write_file_bytes_atomic_python
    cache_attempts = 0

    def fail_first_cache_refresh(path: Path, raw: bytes) -> None:
        nonlocal cache_attempts
        cache_attempts += 1
        if cache_attempts == 1:
            raise OSError("synthetic cache failure")
        real_atomic_write(path, raw)

    monkeypatch.setattr(app_paths, "_write_file_bytes_via_powershell", commit_visible)
    monkeypatch.setattr(app_paths, "_write_file_bytes_atomic_python", fail_first_cache_refresh)
    monkeypatch.setattr(
        app_paths,
        "_read_file_bytes_via_powershell",
        lambda path: visible_bytes["payload"],
    )

    save_json_data_atomic(runtime_path, {"version": 2})

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}
    assert app_paths.load_json_data(runtime_path) == {"version": 2}
    runtime_path.write_text('{"version": 0}', encoding="utf-8")
    assert app_paths.load_json_data(runtime_path) == {"version": 2}
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 2}


def test_store_load_uses_visible_authoritative_file_over_stale_runtime_cache(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)
    monkeypatch.setattr(
        app_paths,
        "_read_file_bytes_via_powershell",
        lambda path: b'{"version": 2}',
    )

    loaded = app_paths.load_json_data(runtime_path)

    assert loaded == {"version": 2}
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 2}


@pytest.mark.parametrize("visible_bytes", [b"", b'{"version":'])
def test_store_load_exposes_corrupt_visible_file_without_runtime_fallback(
    tmp_path,
    monkeypatch,
    visible_bytes,
):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: visible_bytes)

    with pytest.raises(json.JSONDecodeError):
        app_paths.load_json_data(runtime_path)

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}


def test_store_load_reports_missing_visible_file_without_runtime_fallback(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: None)

    with pytest.raises(FileNotFoundError):
        app_paths.load_json_data(runtime_path)

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}


def test_store_load_reports_visible_read_error_without_runtime_fallback(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "state.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text('{"version": 1}', encoding="utf-8")
    _force_store_python_bridge(monkeypatch, runtime_root, visible_root)

    def fail_visible_read(path: Path) -> bytes:
        raise PermissionError("synthetic visible read failure")

    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", fail_visible_read)

    with pytest.raises(PermissionError, match="synthetic visible read failure"):
        app_paths.load_json_data(runtime_path)

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"version": 1}


def test_store_powershell_atomic_write_uses_unique_temp_flush_replace_and_cleanup(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    class DummyCompleted:
        stdout = ""
        stderr = ""
        returncode = 0

    def capture_command(command: str, *, input_text: str | None = None):
        captured["command"] = command
        captured["input_text"] = input_text or ""
        return DummyCompleted()

    monkeypatch.setattr(app_paths, "_run_powershell_command", capture_command)

    app_paths._write_file_bytes_via_powershell(tmp_path / "state.json", b'{"version": 2}')

    command = captured["command"]
    assert captured["input_text"] not in command
    assert "NewGuid" in command
    assert "FileMode]::CreateNew" in command
    assert "FlushFileBuffers" in command
    assert "MoveFileEx" in command
    assert "Remove-Item" in command
    flush_call = "[EneAtomicFileNativeMethods]::FlushFileBuffers"
    replace_call = "[EneAtomicFileNativeMethods]::MoveFileEx"
    assert f"{replace_call}($temp, $path, 9)" in command
    assert command.index("FileMode]::CreateNew") < command.index(flush_call)
    assert command.index(flush_call) < command.index(replace_call)
    assert command.index(replace_call) < command.rindex("Remove-Item")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell atomic bridge is Windows-only")
def test_powershell_atomic_write_round_trips_empty_and_nonempty_bytes(tmp_path):
    target = tmp_path / "state.bin"

    app_paths._write_file_bytes_via_powershell(target, b"")
    assert app_paths._read_file_bytes_via_powershell(target) == b""

    app_paths._write_file_bytes_via_powershell(target, b"synthetic-state")
    assert app_paths._read_file_bytes_via_powershell(target) == b"synthetic-state"
    assert app_paths._read_file_bytes_via_powershell(tmp_path / "missing.bin") is None


def test_gitignore_covers_life_and_existing_runtime_files():
    repository_root = Path(__file__).resolve().parents[1]
    ignored_lines = {
        line.strip()
        for line in (repository_root / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "prompts/life_world.md",
        "life_records.json",
        "life_session_state.json",
        "life_session_state.lock",
        ".*.json.*.tmp",
        ".env*",
        "diary.json",
        "memory.json",
        "user_profile.json",
        "config.json",
        "api_keys.json",
        "obs_config.json",
        "mood_state.json",
        "calendar.json",
    } <= ignored_lines


def test_get_user_data_dir_prefers_explicit_env_override(tmp_path, monkeypatch):
    from src.core import app_paths

    target = tmp_path / "ene-data"
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(target))

    assert app_paths.get_user_data_dir() == target


def test_resolve_runtime_resource_path_prefers_user_data_then_bundle(tmp_path):
    from src.core.app_paths import resolve_runtime_resource_path

    user_root = tmp_path / "user"
    bundle_root = tmp_path / "bundle"
    relative_path = "assets/live2d_models/sample/sample.model3.json"

    bundle_file = bundle_root / relative_path
    bundle_file.parent.mkdir(parents=True, exist_ok=True)
    bundle_file.write_text("bundle", encoding="utf-8-sig")

    user_file = user_root / relative_path
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("user", encoding="utf-8-sig")

    resolved = resolve_runtime_resource_path(
        relative_path,
        user_root=user_root,
        bundle_root=bundle_root,
    )

    assert resolved == user_file.resolve()


def test_relativize_for_storage_returns_relative_path_for_known_roots(tmp_path):
    from src.core.app_paths import relativize_for_storage

    user_root = tmp_path / "user"
    target = user_root / "assets" / "live2d_models" / "sample.model3.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8-sig")

    stored = relativize_for_storage(
        str(target),
        user_root=user_root,
        bundle_root=tmp_path / "bundle",
    )

    assert stored == "assets/live2d_models/sample.model3.json"


def test_load_json_data_prefers_visible_roaming_under_store_python(tmp_path, monkeypatch):
    import json

    from src.core import app_paths

    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "config.json"
    visible_path = visible_root / "config.json"
    payload = {
        "ui_language": "ko",
        "embedding_api_keys": {"voyage": "real-visible-key"},
    }

    monkeypatch.delenv("ENE_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths, "is_windows_store_python_runtime", lambda: True)
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: runtime_root)
    monkeypatch.setattr(app_paths, "get_visible_user_data_dir", lambda app_name=app_paths.APP_NAME: visible_root)
    monkeypatch.setattr(
        app_paths,
        "_read_file_bytes_via_powershell",
        lambda path: json.dumps(payload, ensure_ascii=False).encode("utf-8-sig") if path == visible_path else None,
    )

    loaded = app_paths.load_json_data(runtime_path, encoding="utf-8-sig")

    assert loaded["ui_language"] == "ko"
    assert loaded["embedding_api_keys"]["voyage"] == "real-visible-key"
    assert runtime_path.exists()


def test_save_json_data_mirrors_visible_roaming_under_store_python(tmp_path, monkeypatch):
    import json

    from src.core import app_paths

    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    runtime_path = runtime_root / "api_keys.json"
    visible_path = visible_root / "api_keys.json"
    payload = {
        "embedding_api_keys": {"voyage": "saved-visible-key"},
    }
    mirrored: list[tuple[Path, dict]] = []

    monkeypatch.delenv("ENE_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths, "is_windows_store_python_runtime", lambda: True)
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: runtime_root)
    monkeypatch.setattr(app_paths, "get_visible_user_data_dir", lambda app_name=app_paths.APP_NAME: visible_root)

    def _capture_write(path: Path, raw_payload: bytes) -> None:
        mirrored.append((path, json.loads(raw_payload.decode("utf-8-sig"))))

    monkeypatch.setattr(app_paths, "_write_file_bytes_via_powershell", _capture_write)

    app_paths.save_json_data(runtime_path, payload)

    assert not runtime_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == payload
    assert mirrored == [(visible_path, payload)]


def test_powershell_helper_reads_output_as_utf8(monkeypatch):
    from src.core import app_paths

    captured = {}

    class DummyCompleted:
        stdout = ""
        stderr = ""
        returncode = 0

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return DummyCompleted()

    monkeypatch.setattr(app_paths.subprocess, "run", fake_run)

    app_paths._run_powershell_command("[Console]::Write('확인')")

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
