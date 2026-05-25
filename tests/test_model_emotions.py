def test_get_available_model_emotions_reads_model_emotions_folder(tmp_path):
    from src.core.model_emotions import get_available_model_emotions

    model_path = tmp_path / "assets" / "live2d_models" / "sample" / "sample.model3.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8-sig")

    emotions_dir = model_path.parent / "emotions"
    emotions_dir.mkdir(parents=True, exist_ok=True)
    (emotions_dir / "joy.exp3.json").write_text("{}", encoding="utf-8-sig")
    (emotions_dir / "normal.exp3.json").write_text("{}", encoding="utf-8-sig")
    (emotions_dir / "smile.exp3.json").write_text("{}", encoding="utf-8-sig")

    emotions = get_available_model_emotions(
        settings_source={"model_json_path": "assets/live2d_models/sample/sample.model3.json"},
        base_path=tmp_path,
    )

    assert emotions == ["normal", "joy", "smile"]


def test_overlay_window_resolve_model_path_payload_includes_available_emotions(tmp_path):
    from src.core.overlay_window import OverlayWindow

    model_path = tmp_path / "assets" / "live2d_models" / "sample" / "sample.model3.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8-sig")

    emotions_dir = model_path.parent / "emotions"
    emotions_dir.mkdir(parents=True, exist_ok=True)
    (emotions_dir / "normal.exp3.json").write_text("{}", encoding="utf-8-sig")
    (emotions_dir / "joy.exp3.json").write_text("{}", encoding="utf-8-sig")

    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type("DummySettings", (), {"config": {}})()
    window._get_base_path = lambda: tmp_path

    payload = OverlayWindow._resolve_model_path_payload(
        window,
        {"model_json_path": "assets/live2d_models/sample/sample.model3.json"},
    )

    assert payload["availableEmotions"] == ["normal", "joy"]
    assert payload["emotionsBasePath"].endswith("/emotions/")


def test_resolve_model_json_path_falls_back_to_bundle_root_when_user_copy_is_missing(tmp_path):
    from src.core.model_emotions import resolve_model_json_path

    bundle_root = tmp_path / "bundle"
    model_path = bundle_root / "assets" / "live2d_models" / "sample" / "sample.model3.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8-sig")

    resolved = resolve_model_json_path(
        settings_source={"model_json_path": "assets/live2d_models/sample/sample.model3.json"},
        base_path=bundle_root,
    )

    assert resolved == model_path.resolve()


def test_default_model_json_path_points_to_bundled_hiyori_model():
    from src.core.model_emotions import DEFAULT_MODEL_JSON_PATH, get_available_model_emotions

    assert DEFAULT_MODEL_JSON_PATH == "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json"
    root = Path(__file__).resolve().parents[1]
    assert (root / DEFAULT_MODEL_JSON_PATH).exists()
    assert get_available_model_emotions(
        settings_source={"model_json_path": DEFAULT_MODEL_JSON_PATH},
        base_path=root,
        fallback_emotions=["normal", "eyeclose", "shy"],
    ) == ["normal"]


def test_existing_model_without_emotions_uses_normal_only_even_with_fallback(tmp_path):
    from src.core.model_emotions import get_available_model_emotions

    model_path = tmp_path / "assets" / "live2d_models" / "plain" / "plain.model3.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8-sig")

    emotions = get_available_model_emotions(
        settings_source={"model_json_path": "assets/live2d_models/plain/plain.model3.json"},
        base_path=tmp_path,
        fallback_emotions=["normal", "eyeclose", "shy"],
    )

    assert emotions == ["normal"]
from pathlib import Path
