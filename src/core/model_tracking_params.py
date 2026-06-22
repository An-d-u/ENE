import json
import re
from pathlib import Path


TRACKING_DEFAULT_PARAMS = {
    "angleX": "ParamAngleX",
    "angleY": "ParamAngleY",
    "angleZ": "ParamAngleZ",
    "bodyAngleX": "ParamBodyAngleX",
    "bodyAngleY": "ParamBodyAngleY",
    "bodyAngleZ": "ParamBodyAngleZ",
    "eyeBallX": "ParamEyeBallX",
    "eyeBallY": "ParamEyeBallY",
    "breath": "ParamBreath",
}

VTUBE_FACE_INPUTS = {
    "FaceAngleX": "angleX",
    "FaceAngleY": "angleY",
    "FaceAngleZ": "angleZ",
}

DISPLAY_NAME_HINTS = {
    "angleX": ("angle x", "anglex", "?? x", "??x"),
    "angleY": ("angle y", "angley", "?? y", "??y"),
    "angleZ": ("angle z", "anglez", "?? z", "??z"),
    "bodyAngleX": (
        "body angle x",
        "body anglex",
        "body rotation x",
        "body x",
        "bodyx",
    ),
    "bodyAngleY": (
        "body angle y",
        "body angley",
        "body rotation y",
        "body y",
        "bodyy",
    ),
    "bodyAngleZ": (
        "body angle z",
        "body anglez",
        "body rotation z",
        "body twist z",
        "body z",
        "bodyz",
    ),
}


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _model_stem(model_path: Path) -> str:
    name = model_path.name
    if name.endswith(".model3.json"):
        return name[: -len(".model3.json")]
    return model_path.stem


def _candidate_sidecar_path(model_path: Path, suffix: str) -> Path:
    return model_path.with_name(f"{_model_stem(model_path)}{suffix}")


def _load_parameter_display_items(model_path: Path) -> list[dict]:
    model_payload = _read_json(model_path)
    file_references = model_payload.get("FileReferences", {}) if isinstance(model_payload, dict) else {}
    raw_display_info = file_references.get("DisplayInfo") if isinstance(file_references, dict) else None
    if isinstance(raw_display_info, str) and raw_display_info.strip():
        cdi_path = (model_path.parent / raw_display_info).resolve()
    else:
        cdi_path = _candidate_sidecar_path(model_path, ".cdi3.json")

    cdi_payload = _read_json(cdi_path)
    parameters = cdi_payload.get("Parameters", [])
    return [item for item in parameters if isinstance(item, dict)]


def _available_parameter_ids(model_path: Path) -> set[str]:
    ids: set[str] = set()
    for item in _load_parameter_display_items(model_path):
        param_id = str(item.get("Id", "")).strip()
        if param_id:
            ids.add(param_id)
    return ids


def _iter_vtube_parameter_settings(payload) -> list[dict]:
    found: list[dict] = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if isinstance(value.get("Input"), str) and isinstance(value.get("OutputLive2D"), str):
                found.append(value)
            for item in value.values():
                walk(item)

    walk(payload)
    return found


def _apply_vtube_face_angle_mapping(mapping: dict[str, str], model_path: Path, available_ids: set[str]) -> None:
    vtube_path = _candidate_sidecar_path(model_path, ".vtube.json")
    vtube_payload = _read_json(vtube_path)
    if not vtube_payload:
        return

    for item in _iter_vtube_parameter_settings(vtube_payload):
        key = VTUBE_FACE_INPUTS.get(str(item.get("Input", "")).strip())
        output_id = str(item.get("OutputLive2D", "")).strip()
        if not key or not output_id:
            continue
        if available_ids and output_id not in available_ids:
            continue
        preferred_id = TRACKING_DEFAULT_PARAMS.get(key, "")
        current_id = mapping.get(key, "")
        if current_id == preferred_id:
            continue
        if current_id and output_id != preferred_id:
            continue
        mapping[key] = output_id


def _normalize_display_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _apply_display_name_fallback(mapping: dict[str, str], model_path: Path, available_ids: set[str]) -> None:
    if not available_ids:
        return
    for key, hints in DISPLAY_NAME_HINTS.items():
        if mapping.get(key):
            continue
        for item in _load_parameter_display_items(model_path):
            param_id = str(item.get("Id", "")).strip()
            name = _normalize_display_name(str(item.get("Name", "")))
            compact_name = name.replace(" ", "")
            if param_id and param_id in available_ids and (name in hints or compact_name in hints):
                mapping[key] = param_id
                break


def load_model_tracking_parameter_map_for_model_json(model_path) -> dict[str, str]:
    path = Path(model_path)
    available_ids = _available_parameter_ids(path)
    mapping: dict[str, str] = {}

    _apply_vtube_face_angle_mapping(mapping, path, available_ids)

    for key, param_id in TRACKING_DEFAULT_PARAMS.items():
        if key not in mapping and (not available_ids or param_id in available_ids):
            mapping[key] = param_id

    _apply_display_name_fallback(mapping, path, available_ids)
    return mapping
