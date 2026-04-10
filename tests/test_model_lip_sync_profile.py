import json

from src.core.model_lip_sync_profile import (
    build_model_lip_sync_profile_from_params,
    load_model_lip_sync_profile,
    load_model_lip_sync_profile_for_model_json,
)


def test_detects_vbridger_mode_from_available_params():
    profile = build_model_lip_sync_profile_from_params(
        {
            "ParamMouthOpenY",
            "ParamMouthForm",
            "ParamMouthFunnel",
            "ParamMouthPuckerWiden",
            "ParamJawOpen",
        }
    )

    assert profile.mode == "vbridger"


def test_uses_auto_detected_profile_when_override_file_missing(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    profile = load_model_lip_sync_profile(
        model_dir=model_dir,
        available_params={"ParamMouthOpenY", "ParamMouthForm"},
    )

    assert profile.mode == "open_form"
    assert profile.param_bindings["mouth_open"] == "ParamMouthOpenY"


def test_override_file_only_replaces_specified_keys(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    override_path = model_dir / "lip_sync_profile.json"
    override_path.write_text(
        json.dumps(
            {
                "mode": "vbridger",
                "smoothing": {"shape_blend_ms": 90},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    profile = load_model_lip_sync_profile(
        model_dir=model_dir,
        available_params={"ParamMouthOpenY"},
    )

    assert profile.mode == "vbridger"
    assert profile.smoothing["shape_blend_ms"] == 90
    assert profile.fallback["confidence_threshold"] == 0.55


def test_invalid_override_file_falls_back_to_auto_detected_profile(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    override_path = model_dir / "lip_sync_profile.json"
    override_path.write_text("{broken-json", encoding="utf-8-sig")

    profile = load_model_lip_sync_profile(
        model_dir=model_dir,
        available_params={"ParamMouthOpenY"},
    )

    assert profile.mode == "open_only"


def test_model_json_loader_detects_vbridger_profile_for_jksalt_like_params(tmp_path):
    model_dir = tmp_path / "jksalt"
    model_dir.mkdir()
    model_path = model_dir / "jksalt.model3.json"
    model_path.write_text(
        json.dumps({"Groups": []}, ensure_ascii=False),
        encoding="utf-8-sig",
    )
    model_path.with_suffix(".cdi3.json").write_text(
        json.dumps(
            {
                "Parameters": [
                    {"Id": "ParamMouthOpenY"},
                    {"Id": "ParamMouthForm"},
                    {"Id": "ParamMouthFunnel"},
                    {"Id": "ParamMouthPuckerWiden"},
                    {"Id": "ParamJawOpen"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    profile = load_model_lip_sync_profile_for_model_json(model_path)

    assert profile.mode == "vbridger"
    assert profile.viseme_map["O"]["mouth_funnel"] > 0.3
