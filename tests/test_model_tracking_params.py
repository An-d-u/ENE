import json
import shutil
from contextlib import contextmanager
from pathlib import Path

from src.core.model_tracking_params import load_model_tracking_parameter_map_for_model_json


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")


@contextmanager
def _workspace_tmp(name):
    root = Path(__file__).resolve().parent / ".tmp_model_tracking_params" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tracking_parameter_map_prefers_vtube_face_angle_outputs():
    with _workspace_tmp("mechanical") as model_dir:
        model_path = model_dir / "Mechanical_Girl_Zero.model3.json"
        _write_json(model_path, {"Version": 3})
        _write_json(
            model_dir / "Mechanical_Girl_Zero.cdi3.json",
            {
                "Parameters": [
                    {"Id": "ParamAngleX2", "Name": "Angle X*"},
                    {"Id": "ParamAngleX3", "Name": "Angle Y*"},
                    {"Id": "ParamAngleX4", "Name": "Angle Z*"},
                    {"Id": "ParamAngleX", "Name": "Angle X"},
                    {"Id": "ParamAngleY", "Name": "Angle Y"},
                    {"Id": "ParamEyeBallX", "Name": "Eyeball X"},
                ]
            },
        )
        _write_json(
            model_dir / "Mechanical_Girl_Zero.vtube.json",
            {
                "ParameterSettings": [
                    {"Input": "FaceAngleX", "OutputLive2D": "ParamAngleX2"},
                    {"Input": "FaceAngleY", "OutputLive2D": "ParamAngleX3"},
                    {"Input": "FaceAngleZ", "OutputLive2D": "ParamAngleX4"},
                ]
            },
        )

        mapping = load_model_tracking_parameter_map_for_model_json(model_path)

    assert mapping["angleX"] == "ParamAngleX2"
    assert mapping["angleY"] == "ParamAngleX3"
    assert mapping["angleZ"] == "ParamAngleX4"
    assert mapping["eyeBallX"] == "ParamEyeBallX"


def test_tracking_parameter_map_falls_back_to_standard_angle_params():
    with _workspace_tmp("hiyori") as model_dir:
        model_path = model_dir / "hiyori.model3.json"
        _write_json(model_path, {"Version": 3})
        _write_json(
            model_dir / "hiyori.cdi3.json",
            {
                "Parameters": [
                    {"Id": "ParamAngleX", "Name": "Angle X"},
                    {"Id": "ParamAngleY", "Name": "Angle Y"},
                    {"Id": "ParamAngleZ", "Name": "Angle Z"},
                ]
            },
        )

        mapping = load_model_tracking_parameter_map_for_model_json(model_path)

    assert mapping["angleX"] == "ParamAngleX"
    assert mapping["angleY"] == "ParamAngleY"
    assert mapping["angleZ"] == "ParamAngleZ"


def test_tracking_parameter_map_prefers_face_angle_output_over_body_duplicate():
    with _workspace_tmp("duplicate-vtube") as model_dir:
        model_path = model_dir / "sample.model3.json"
        _write_json(model_path, {"Version": 3})
        _write_json(
            model_dir / "sample.cdi3.json",
            {
                "Parameters": [
                    {"Id": "ParamAngleX"},
                    {"Id": "ParamAngleY"},
                    {"Id": "ParamAngleZ"},
                    {"Id": "ParamBodyAngleX"},
                    {"Id": "ParamBodyAngleY"},
                    {"Id": "ParamBodyAngleZ"},
                ]
            },
        )
        _write_json(
            model_dir / "sample.vtube.json",
            {
                "ParameterSettings": [
                    {"Input": "FaceAngleX", "OutputLive2D": "ParamAngleX"},
                    {"Input": "FaceAngleX", "OutputLive2D": "ParamBodyAngleX"},
                    {"Input": "FaceAngleY", "OutputLive2D": "ParamAngleY"},
                    {"Input": "FaceAngleY", "OutputLive2D": "ParamBodyAngleY"},
                    {"Input": "FaceAngleZ", "OutputLive2D": "ParamAngleZ"},
                    {"Input": "FaceAngleZ", "OutputLive2D": "ParamBodyAngleZ"},
                ]
            },
        )

        mapping = load_model_tracking_parameter_map_for_model_json(model_path)

    assert mapping["angleX"] == "ParamAngleX"
    assert mapping["angleY"] == "ParamAngleY"
    assert mapping["angleZ"] == "ParamAngleZ"


def test_overlay_window_model_config_includes_tracking_parameter_map():
    from src.core.overlay_window import OverlayWindow

    with _workspace_tmp("overlay") as root:
        model_path = root / "assets" / "live2d_models" / "sample" / "sample.model3.json"
        model_path.parent.mkdir(parents=True)
        _write_json(model_path, {"Version": 3})
        _write_json(
            model_path.with_name("sample.cdi3.json"),
            {"Parameters": [{"Id": "ParamAngleX"}, {"Id": "ParamAngleY"}]},
        )

        window = OverlayWindow.__new__(OverlayWindow)
        window.settings = type("DummySettings", (), {"config": {}})()
        window._get_base_path = lambda: root

        payload = OverlayWindow._resolve_model_config_payload(
            window,
            {"model_json_path": "assets/live2d_models/sample/sample.model3.json"},
        )

    assert payload["trackingParameterMap"]["angleX"] == "ParamAngleX"
    assert payload["trackingParameterMap"]["angleY"] == "ParamAngleY"
