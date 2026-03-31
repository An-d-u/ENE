from pathlib import Path


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

    app_paths.save_json_data(runtime_path, payload, encoding="utf-8-sig")

    assert json.loads(runtime_path.read_text(encoding="utf-8-sig")) == payload
    assert mirrored == [(visible_path, payload)]
