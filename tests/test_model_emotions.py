from pathlib import Path


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
