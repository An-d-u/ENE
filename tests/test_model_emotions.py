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


def test_overlay_window_syncs_performance_settings_to_webview(tmp_path):
    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = type("DummySettings", (), {"config": {"performance_engine_enabled": False}})()
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_performance_engine_settings_to_js(
        overlay,
        {
            "performance_engine_enabled": True,
            "performance_intensity": 1.2,
            "speech_reactivity": 0.8,
            "idle_micro_motion": 0.25,
            "show_motion_debug_overlay": True,
        },
    )

    assert captured
    assert 'window.enePerformanceConfig = {"enabled": true, "intensity": 1.2, "speechReactivity": 0.8, "idleMicroMotion": 0.25, "showDebugOverlay": true};' in captured[-1]
    assert "window.setPerformanceEngineConfig(window.enePerformanceConfig);" in captured[-1]
