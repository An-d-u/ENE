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
