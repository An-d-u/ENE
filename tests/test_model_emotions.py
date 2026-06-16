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
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
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
def test_overlay_window_resolves_parameter_overrides_for_current_model_key():
    from src.core.overlay_window import OverlayWindow

    model_key = "assets/live2d_models/sample/sample.model3.json"
    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type(
        "DummySettings",
        (),
        {
            "config": {
                "model_json_path": r"assets\live2d_models\sample\sample.model3.json",
                "live2d_parameter_overrides": {
                    model_key: {
                        "values": {"ParamAngleX": 7, " ParamAngleY ": 1.5},
                        "favorites": ["ParamAngleX", " ParamAngleY "],
                    },
                },
            },
        },
    )()

    assert OverlayWindow._resolve_model_key(window) == model_key
    assert OverlayWindow._resolve_live2d_parameter_overrides_payload(window) == {
        "values": {"ParamAngleX": 7.0, "ParamAngleY": 1.5},
        "favorites": ["ParamAngleX", "ParamAngleY"],
    }


def test_overlay_window_resolves_live2d_parameter_display_info(tmp_path):
    from src.core.overlay_window import OverlayWindow

    json_module = __import__("json")
    model_path = tmp_path / "assets" / "live2d_models" / "sample" / "sample.model3.json"
    model_path.parent.mkdir(parents=True)
    model_path.write_text(
        json_module.dumps(
            {
                "Version": 3,
                "FileReferences": {
                    "DisplayInfo": "sample.cdi3.json",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    model_path.with_name("sample.cdi3.json").write_text(
        json_module.dumps(
            {
                "Version": 3,
                "Parameters": [
                    {"Id": "ParamRibbon", "GroupId": "ParamGroupDecor", "Name": "리본"},
                    {"Id": "ParamEyeLOpen", "GroupId": "ParamGroupEyes", "Name": "왼쪽 눈 뜨기"},
                ],
                "ParameterGroups": [
                    {"Id": "ParamGroupDecor", "GroupId": "", "Name": "장식"},
                    {"Id": "ParamGroupEyes", "GroupId": "", "Name": "눈"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type(
        "DummySettings",
        (),
        {"config": {"model_json_path": "assets/live2d_models/sample/sample.model3.json"}},
    )()
    window._get_base_path = lambda: tmp_path

    assert OverlayWindow._resolve_live2d_parameter_display_info_payload(window) == {
        "parameters": {
            "ParamRibbon": {
                "name": "리본",
                "groupId": "ParamGroupDecor",
                "groupName": "장식",
            },
            "ParamEyeLOpen": {
                "name": "왼쪽 눈 뜨기",
                "groupId": "ParamGroupEyes",
                "groupName": "눈",
            },
        },
        "groups": {
            "ParamGroupDecor": {
                "name": "장식",
                "parentGroupId": "",
            },
            "ParamGroupEyes": {
                "name": "눈",
                "parentGroupId": "",
            },
        },
    }


def test_overlay_window_parameter_overrides_fall_back_when_missing_or_malformed():
    from src.core.overlay_window import OverlayWindow

    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type("DummySettings", (), {"config": {}})()
    malformed_sources = [
        {},
        {"live2d_parameter_overrides": []},
        {
            "model_json_path": "assets/live2d_models/sample/sample.model3.json",
            "live2d_parameter_overrides": {
                "assets/live2d_models/sample/sample.model3.json": [],
            },
        },
        {
            "model_json_path": "assets/live2d_models/sample/sample.model3.json",
            "live2d_parameter_overrides": {
                "assets/live2d_models/sample/sample.model3.json": {
                    "values": [],
                    "favorites": {},
                },
            },
        },
    ]

    for source in malformed_sources:
        assert OverlayWindow._resolve_live2d_parameter_overrides_payload(window, source) == {
            "values": {},
            "favorites": [],
        }


def test_overlay_window_parameter_overrides_reject_malformed_saved_values_for_current_model():
    from src.core.overlay_window import OverlayWindow

    model_key = "assets/live2d_models/sample/sample.model3.json"
    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type("DummySettings", (), {"config": {}})()
    malformed_payloads = [
        {"values": {"ParamX": True}, "favorites": []},
        {"values": {"ParamX": "1.0"}, "favorites": []},
        {"values": {}, "favorites": [123]},
        {"values": {}, "favorites": [""]},
    ]

    for payload in malformed_payloads:
        source = {
            "model_json_path": model_key,
            "live2d_parameter_overrides": {
                model_key: payload,
            },
        }
        assert OverlayWindow._resolve_live2d_parameter_overrides_payload(window, source) == {
            "values": {},
            "favorites": [],
        }


def test_overlay_window_preview_settings_preserves_saved_parameter_overrides(tmp_path):
    from src.core.overlay_window import OverlayWindow

    model_key = "assets/live2d_models/sample/sample.model3.json"
    model_path = tmp_path / "assets" / "live2d_models" / "sample" / "sample.model3.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8-sig")

    emitted_scripts = []

    class DummySettings:
        config = {
            "model_json_path": model_key,
            "model_scale": 1.0,
            "model_x_percent": 50,
            "model_y_percent": 50,
            "live2d_parameter_overrides": {
                model_key: {
                    "values": {"ParamAngleX": 12},
                    "favorites": ["ParamAngleX"],
                },
            },
        }

        def get(self, key, default=None):
            return self.config.get(key, default)

    class DummyPage:
        def runJavaScript(self, script):
            emitted_scripts.append(script)

    class DummyWebView:
        def page(self):
            return DummyPage()

    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = DummySettings()
    window._page_loaded = False
    window._get_base_path = lambda: tmp_path
    window._apply_drag_bar_theme = lambda settings_override=None: None
    window.move = lambda *args: None
    window.resize = lambda *args: None
    window.drag_bar = type("DummyDragBar", (), {"setVisible": lambda self, visible: None})()
    window.web_view = DummyWebView()

    original_config = dict(window.settings.config)
    OverlayWindow.preview_settings(
        window,
        {
            "model_json_path": model_key,
            "model_scale": 1.25,
        },
    )

    assert window.settings.config == original_config
    assert emitted_scripts
    assert 'parameterOverrides: {"values": {"ParamAngleX": 12.0}, "favorites": ["ParamAngleX"]}' in emitted_scripts[0]


def test_discover_image_avatar_emotions_reads_supported_image_files(tmp_path):
    from src.core.image_avatar import discover_image_avatar_emotions

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "sad.webp").write_bytes(b"fake")
    (avatar_dir / "joy.png").write_bytes(b"fake")
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "ignore.txt").write_text("x", encoding="utf-8-sig")

    emotions = discover_image_avatar_emotions(avatar_dir)

    assert emotions == ["normal", "joy", "sad"]


def test_build_image_avatar_payload_prefers_png_and_includes_file_placements(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.webp").write_bytes(b"fake")
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "joy.jpg").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {
            "image_avatar_folder": "avatar_images/sample",
            "image_avatar_placements": {
                "avatar_images/sample/joy.jpg": {
                    "scale": 1.2,
                    "x_percent": 55,
                    "y_percent": 45,
                }
            },
        },
        base_path=tmp_path,
    )

    assert payload["availableEmotions"] == ["normal", "joy"]
    assert payload["images"]["normal"]["path"].endswith("/normal.png")
    assert payload["images"]["normal"]["storageKey"] == "avatar_images/sample/normal.png"
    assert payload["images"]["joy"]["placement"] == {"scale": 1.2, "xPercent": 55, "yPercent": 45}
    assert payload["error"] == ""


def test_build_image_avatar_payload_prefers_user_data_for_relative_folder(tmp_path, monkeypatch):
    from src.core import app_paths
    from src.core.image_avatar import build_image_avatar_payload

    user_root = tmp_path / "user_data"
    bundle_root = tmp_path / "bundle"
    avatar_dir = user_root / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    bundle_root.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    monkeypatch.setenv("ENE_USER_DATA_DIR", str(user_root))
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: user_root)

    payload = build_image_avatar_payload(
        {"image_avatar_folder": "avatar_images/sample"},
        base_path=bundle_root,
    )

    assert payload["availableEmotions"] == ["normal"]
    assert payload["images"]["normal"]["path"] == (avatar_dir / "normal.png").resolve().as_uri()
    assert payload["images"]["normal"]["storageKey"] == "avatar_images/sample/normal.png"
    assert payload["folderPath"] == avatar_dir.resolve().as_uri()
    assert payload["error"] == ""


def test_build_image_avatar_payload_uses_relative_storage_key_for_default_folder(tmp_path, monkeypatch):
    from src.core import app_paths
    from src.core.image_avatar import build_image_avatar_payload

    user_root = tmp_path / "user_data"
    bundle_root = tmp_path / "bundle"
    avatar_dir = user_root / "avatar_images"
    avatar_dir.mkdir(parents=True)
    bundle_root.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    monkeypatch.setenv("ENE_USER_DATA_DIR", str(user_root))
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: user_root)

    payload = build_image_avatar_payload(
        {
            "image_avatar_placements": {
                "avatar_images/normal.png": {
                    "scale": 1.25,
                    "x_percent": 60,
                    "y_percent": 40,
                }
            },
        },
        base_path=bundle_root,
    )

    assert payload["availableEmotions"] == ["normal"]
    assert payload["images"]["normal"]["path"] == (avatar_dir / "normal.png").resolve().as_uri()
    assert payload["images"]["normal"]["storageKey"] == "avatar_images/normal.png"
    assert payload["images"]["normal"]["placement"] == {
        "scale": 1.25,
        "xPercent": 60,
        "yPercent": 40,
    }
    assert payload["folderPath"] == avatar_dir.resolve().as_uri()
    assert payload["error"] == ""


def test_build_image_avatar_payload_uses_relative_storage_key_for_absolute_folder_inside_base_path(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    bundle_root = tmp_path / "bundle"
    avatar_dir = bundle_root / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {
            "image_avatar_folder": str(avatar_dir),
            "image_avatar_placements": {
                "avatar_images/sample/normal.png": {
                    "scale": 1.35,
                    "x_percent": 65,
                    "y_percent": 35,
                }
            },
        },
        base_path=bundle_root,
    )

    assert payload["availableEmotions"] == ["normal"]
    assert payload["images"]["normal"]["path"] == (avatar_dir / "normal.png").resolve().as_uri()
    assert payload["images"]["normal"]["storageKey"] == "avatar_images/sample/normal.png"
    assert payload["images"]["normal"]["placement"] == {
        "scale": 1.35,
        "xPercent": 65,
        "yPercent": 35,
    }
    assert payload["error"] == ""


def test_build_image_avatar_payload_uses_normalized_absolute_storage_key_for_external_folder(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    bundle_root = tmp_path / "bundle"
    external_dir = tmp_path / "external" / "avatars"
    bundle_root.mkdir(parents=True)
    external_dir.mkdir(parents=True)
    (external_dir / "normal.png").write_bytes(b"fake")
    raw_folder = str(external_dir / ".." / "avatars").replace("\\", "/")
    storage_key = f"{raw_folder}/normal.png"

    payload = build_image_avatar_payload(
        {
            "image_avatar_folder": raw_folder,
            "image_avatar_placements": {
                storage_key: {
                    "scale": 1.4,
                    "x_percent": 70,
                    "y_percent": 30,
                }
            },
        },
        base_path=bundle_root,
    )

    assert payload["availableEmotions"] == ["normal"]
    assert payload["images"]["normal"]["path"] == (external_dir / "normal.png").resolve().as_uri()
    assert payload["images"]["normal"]["storageKey"] == storage_key
    assert payload["images"]["normal"]["placement"] == {
        "scale": 1.4,
        "xPercent": 70,
        "yPercent": 30,
    }
    assert payload["error"] == ""


def test_build_image_avatar_payload_reports_missing_normal(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "joy.png").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {"image_avatar_folder": "avatar_images/sample"},
        base_path=tmp_path,
    )

    assert payload["availableEmotions"] == ["normal"]
    assert payload["images"] == {}
    assert payload["error"] == "missing_normal"


def test_build_image_avatar_payload_clamps_saved_placements(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {
            "image_avatar_folder": "avatar_images/sample",
            "image_avatar_placements": {
                "avatar_images/sample/normal.png": {
                    "scale": 3.0,
                    "x_percent": -150,
                    "y_percent": 250,
                }
            },
        },
        base_path=tmp_path,
    )

    assert payload["images"]["normal"]["placement"] == {
        "scale": 2.0,
        "xPercent": -100,
        "yPercent": 200,
    }


def test_build_image_avatar_payload_ignores_non_finite_saved_placements(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {
            "image_avatar_folder": "avatar_images/sample",
            "image_avatar_placements": {
                "avatar_images/sample/normal.png": {
                    "scale": "nan",
                    "x_percent": "inf",
                    "y_percent": "-inf",
                }
            },
        },
        base_path=tmp_path,
    )

    assert payload["images"]["normal"]["placement"] == {
        "scale": 1.0,
        "xPercent": 50,
        "yPercent": 50,
    }


def test_get_available_avatar_emotions_uses_image_avatar_folder_when_image_mode_is_enabled(tmp_path):
    from src.core.model_emotions import get_available_avatar_emotions

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "joy.png").write_bytes(b"fake")

    emotions = get_available_avatar_emotions(
        settings_source={
            "avatar_mode": "image",
            "image_avatar_folder": "avatar_images/sample",
            "model_json_path": "missing.model3.json",
        },
        base_path=tmp_path,
        fallback_emotions=["normal", "fallback"],
    )

    assert emotions == ["normal", "joy"]
