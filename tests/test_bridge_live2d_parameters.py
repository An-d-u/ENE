import json

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
                "pinned": ["ParamRibbon"],
            },
            ensure_ascii=False,
        ),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-b/runtime/model.model3.json",
        json.dumps(
            {
                "values": {"ParamHat": 0.5},
                "pinned": ["ParamHat"],
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

    assert model_a == {"values": {"ParamRibbon": 1.0}, "pinned": ["ParamRibbon"]}
    assert model_b == {"values": {"ParamHat": 0.5}, "pinned": ["ParamHat"]}
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
        "pinned": ["ParamRibbon"],
    }
    assert reloaded_overrides["assets/live2d_models/model-b/runtime/model.model3.json"] == {
        "values": {"ParamHat": 0.5},
        "pinned": ["ParamHat"],
    }


def test_live2d_parameter_overrides_return_empty_payload_for_missing_model(tmp_path):
    bridge, _settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "pinned": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-missing/runtime/model.model3.json")
    ) == {
        "values": {},
        "pinned": [],
    }


def test_live2d_parameter_overrides_reject_non_numeric_value(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": "not-a-number"}, "pinned": ["ParamRibbon"]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "pinned": [],
    }


def test_live2d_parameter_overrides_reject_non_string_pinned_item(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": 1.0}, "pinned": [123]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(
        bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")
    ) == {
        "values": {},
        "pinned": [],
    }
