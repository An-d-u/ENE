import json

from PyQt6.QtCore import QObject

from src.core.bridge import WebBridge
from src.core.settings import Settings


def _bridge_with_settings(tmp_path):
    settings = Settings(
        config_path=str(tmp_path / "config.json"),
        secret_path=str(tmp_path / "api_keys.json"),
    )
    return WebBridge(settings=settings), settings


def _reload_settings(tmp_path):
    return Settings(
        config_path=str(tmp_path / "config.json"),
        secret_path=str(tmp_path / "api_keys.json"),
    )


def test_live2d_parameter_overrides_are_saved_per_model(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps(
            {
                "values": {"ParamRibbon": 1.0},
                "favorites": ["ParamRibbon"],
            },
            ensure_ascii=False,
        ),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-b/runtime/model.model3.json",
        json.dumps(
            {
                "values": {"ParamHat": 0.5},
                "favorites": ["ParamHat"],
            },
            ensure_ascii=False,
        ),
    )

    model_a = json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    )
    model_b = json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-b/runtime/model.model3.json")
    )

    assert model_a == {"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}
    assert model_b == {"values": {"ParamHat": 0.5}, "favorites": ["ParamHat"]}
    assert (
        settings.get("live2d_parameter_overrides")[
            "assets/live2d_models/model-a/runtime/model.model3.json"
        ]["values"]["ParamRibbon"]
        == 1.0
    )
    reloaded_settings = _reload_settings(tmp_path)
    reloaded_overrides = reloaded_settings.get("live2d_parameter_overrides")
    assert reloaded_overrides["assets/live2d_models/model-a/runtime/model.model3.json"] == {
        "values": {"ParamRibbon": 1.0},
        "favorites": ["ParamRibbon"],
    }
    assert reloaded_overrides["assets/live2d_models/model-b/runtime/model.model3.json"] == {
        "values": {"ParamHat": 0.5},
        "favorites": ["ParamHat"],
    }


def test_live2d_parameter_overrides_migrate_legacy_pinned_to_favorites(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)
    model_key = "assets/live2d_models/model-a/runtime/model.model3.json"
    settings.set(
        "live2d_parameter_overrides",
        {
            model_key: {
                "values": {"ParamRibbon": 1.0},
                "pinned": ["ParamRibbon"],
            },
        },
    )

    assert json.loads(bridge.get_live2d_parameter_overrides(model_key)) == {
        "values": {"ParamRibbon": 1.0},
        "favorites": ["ParamRibbon"],
    }

    bridge.save_live2d_parameter_overrides(
        model_key,
        json.dumps({"values": {"ParamRibbon": 0.5}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides")[model_key] == {
        "values": {"ParamRibbon": 0.5},
        "favorites": ["ParamRibbon"],
    }


def test_live2d_parameter_overrides_return_empty_payload_for_missing_model(tmp_path):
    bridge, _settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-missing/runtime/model.model3.json")
    ) == {
        "values": {},
        "favorites": [],
    }


def test_live2d_parameter_overrides_reject_non_numeric_value(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": "not-a-number"}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "favorites": [],
    }


def test_live2d_parameter_overrides_reject_boolean_value(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": True}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "favorites": [],
    }


def test_live2d_parameter_overrides_reject_numeric_string_without_overwriting_existing_payload(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": "1.25"}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {"ParamRibbon": 1.0},
        "favorites": ["ParamRibbon"],
    }
    assert (
        settings.get("live2d_parameter_overrides")[
            "assets/live2d_models/model-a/runtime/model.model3.json"
        ]["values"]["ParamRibbon"]
        == 1.0
    )


def test_live2d_parameter_overrides_reject_non_string_favorites_item(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": [123]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "favorites": [],
    }


def test_live2d_parameter_overrides_reject_empty_favorites_id_without_overwriting_existing_payload(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 0.5}, "favorites": ["   "]}, ensure_ascii=False),
    )

    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {"ParamRibbon": 1.0},
        "favorites": ["ParamRibbon"],
    }
    assert (
        settings.get("live2d_parameter_overrides")[
            "assets/live2d_models/model-a/runtime/model.model3.json"
        ]["values"]["ParamRibbon"]
        == 1.0
    )


def test_live2d_parameter_overrides_reject_oversized_model_key(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "m" * 600,
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}


def test_live2d_parameter_overrides_reject_oversized_parameter_id(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)
    long_param_id = "Param" + ("Ribbon" * 30)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {long_param_id: 1.0}, "favorites": []}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}


def test_live2d_parameter_overrides_reject_too_many_entries(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)
    values = {f"ParamDecor{i}": 0.1 for i in range(300)}

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": values, "favorites": []}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}


def test_live2d_parameter_overrides_reject_oversized_payload(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        '{"values":{"ParamRibbon":1.0},"favorites":[],"padding":"' + ("x" * 70000) + '"}',
    )

    assert settings.get("live2d_parameter_overrides") == {}


def test_live2d_parameter_overrides_empty_payload_removes_only_that_model(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "favorites": ["ParamRibbon"]}, ensure_ascii=False),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-b/runtime/model.model3.json",
        json.dumps({"values": {"ParamHat": 0.5}, "favorites": ["ParamHat"]}, ensure_ascii=False),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {}, "favorites": []}, ensure_ascii=False),
    )

    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "favorites": [],
    }
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-b/runtime/model.model3.json")
    ) == {
        "values": {"ParamHat": 0.5},
        "favorites": ["ParamHat"],
    }
    assert settings.get("live2d_parameter_overrides") == {
        "assets/live2d_models/model-b/runtime/model.model3.json": {
            "values": {"ParamHat": 0.5},
            "favorites": ["ParamHat"],
        }
    }


def test_live2d_parameter_bridge_opens_parent_native_inspector(tmp_path):
    bridge, _settings = _bridge_with_settings(tmp_path)
    calls = []

    class _Parent(QObject):
        def open_live2d_parameter_inspector(self):
            calls.append("opened")

    parent = _Parent()
    bridge.setParent(parent)

    bridge.open_live2d_parameter_inspector()

    assert calls == ["opened"]
