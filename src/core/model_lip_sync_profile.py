"""
Live2D 모델별 립싱크 프로파일 해석 유틸리티.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .app_paths import get_bundle_root, resolve_runtime_resource_path
from .model_emotions import DEFAULT_MODEL_JSON_PATH


_DEFAULT_SMOOTHING = {
    "attack_ms": 50,
    "release_ms": 80,
    "shape_blend_ms": 70,
}

_DEFAULT_FALLBACK = {
    "confidence_threshold": 0.55,
    "rms_open_weight": 1.0,
    "viseme_shape_weight": 0.75,
    "max_wait_ms": 120,
}

_DEFAULT_VISEME_MAP = {
    "sil": {
        "mouth_open": 0.0,
        "jaw_open": 0.0,
        "mouth_form": 0.0,
        "mouth_funnel": 0.0,
        "mouth_pucker_widen": 0.0,
        "tongue": 0.0,
    },
    "A": {
        "mouth_open": 0.70,
        "jaw_open": 0.32,
        "mouth_form": 0.10,
        "mouth_funnel": 0.05,
        "mouth_pucker_widen": 0.00,
        "tongue": 0.0,
    },
    "I": {
        "mouth_open": 0.28,
        "jaw_open": 0.10,
        "mouth_form": -0.22,
        "mouth_funnel": 0.00,
        "mouth_pucker_widen": 0.35,
        "tongue": 0.0,
    },
    "U": {
        "mouth_open": 0.22,
        "jaw_open": 0.08,
        "mouth_form": -0.05,
        "mouth_funnel": 0.58,
        "mouth_pucker_widen": -0.18,
        "tongue": 0.0,
    },
    "E": {
        "mouth_open": 0.40,
        "jaw_open": 0.15,
        "mouth_form": -0.12,
        "mouth_funnel": 0.08,
        "mouth_pucker_widen": 0.22,
        "tongue": 0.0,
    },
    "O": {
        "mouth_open": 0.45,
        "jaw_open": 0.18,
        "mouth_form": 0.02,
        "mouth_funnel": 0.42,
        "mouth_pucker_widen": -0.10,
        "tongue": 0.0,
    },
}

_SEMANTIC_BINDINGS = {
    "mouth_open": "ParamMouthOpenY",
    "jaw_open": "ParamJawOpen",
    "mouth_form": "ParamMouthForm",
    "mouth_funnel": "ParamMouthFunnel",
    "mouth_pucker_widen": "ParamMouthPuckerWiden",
    "tongue": "ParamTongue",
}

_DIRECT_PHONEME_PARAM_IDS = (
    "ParamMouthA",
    "ParamMouthI",
    "ParamMouthU",
    "ParamMouthE",
    "ParamMouthO",
)


@dataclass(frozen=True)
class ModelLipSyncProfile:
    """모델 립싱크 적용에 필요한 최종 프로파일."""

    mode: str
    available_params: tuple[str, ...]
    param_bindings: dict[str, str]
    viseme_map: dict[str, dict[str, float]]
    smoothing: dict[str, float]
    fallback: dict[str, float]


def _safe_read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _detect_profile_mode(available_params: set[str]) -> str:
    if all(param in available_params for param in _DIRECT_PHONEME_PARAM_IDS):
        return "phoneme_direct"
    if {
        "ParamMouthOpenY",
        "ParamMouthForm",
        "ParamMouthFunnel",
        "ParamMouthPuckerWiden",
        "ParamJawOpen",
    }.issubset(available_params):
        return "vbridger"
    if {"ParamMouthOpenY", "ParamMouthForm"}.issubset(available_params):
        return "open_form"
    return "open_only"


def _build_param_bindings(mode: str, available_params: set[str]) -> dict[str, str]:
    requested_keys = ["mouth_open"]
    if mode in {"open_form", "vbridger"}:
        requested_keys.append("mouth_form")
    if mode == "vbridger":
        requested_keys.extend(["jaw_open", "mouth_funnel", "mouth_pucker_widen", "tongue"])

    bindings: dict[str, str] = {}
    for key in requested_keys:
        param_id = _SEMANTIC_BINDINGS[key]
        if param_id in available_params:
            bindings[key] = param_id
    return bindings


def _filter_viseme_map_for_bindings(param_bindings: dict[str, str]) -> dict[str, dict[str, float]]:
    allowed_keys = set(param_bindings.keys())
    return {
        viseme: {
            key: value
            for key, value in payload.items()
            if key in allowed_keys
        }
        for viseme, payload in _DEFAULT_VISEME_MAP.items()
    }


def _deep_merge_dict(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_model_lip_sync_profile_from_params(
    available_params: set[str] | tuple[str, ...] | list[str],
    *,
    preferred_mode: str | None = None,
    override_data: dict | None = None,
) -> ModelLipSyncProfile:
    available_param_set = {str(item).strip() for item in (available_params or set()) if str(item).strip()}
    mode = str(preferred_mode or _detect_profile_mode(available_param_set)).strip() or "open_only"
    param_bindings = _build_param_bindings(mode, available_param_set)
    viseme_map = _filter_viseme_map_for_bindings(param_bindings)
    smoothing = dict(_DEFAULT_SMOOTHING)
    fallback = dict(_DEFAULT_FALLBACK)

    override_payload = override_data if isinstance(override_data, dict) else {}
    mode = str(override_payload.get("mode", mode)).strip() or mode
    param_bindings = _deep_merge_dict(param_bindings, override_payload.get("param_bindings", {}))
    viseme_map = _deep_merge_dict(viseme_map, override_payload.get("viseme_map", {}))
    smoothing = _deep_merge_dict(smoothing, override_payload.get("smoothing", {}))
    fallback = _deep_merge_dict(fallback, override_payload.get("fallback", {}))

    valid_bindings = {
        key: value
        for key, value in param_bindings.items()
        if isinstance(value, str) and value.strip()
    }

    return ModelLipSyncProfile(
        mode=mode,
        available_params=tuple(sorted(available_param_set)),
        param_bindings=valid_bindings,
        viseme_map=viseme_map,
        smoothing=smoothing,
        fallback=fallback,
    )


def _extract_params_from_cdi3(cdi3_path: Path) -> set[str]:
    payload = _safe_read_json(cdi3_path)
    params: set[str] = set()
    for item in payload.get("Parameters", []) or []:
        if isinstance(item, dict):
            param_id = str(item.get("Id", "")).strip()
            if param_id:
                params.add(param_id)
    return params


def _extract_params_from_model3(model3_path: Path) -> set[str]:
    payload = _safe_read_json(model3_path)
    params: set[str] = set()
    for group in payload.get("Groups", []) or []:
        for item in group.get("Ids", []) or []:
            param_id = str(item).strip()
            if param_id:
                params.add(param_id)
    return params


def extract_available_model_params(model_json_path: str | Path) -> set[str]:
    model_path = Path(model_json_path)
    params = _extract_params_from_model3(model_path)
    cdi3_path = model_path.with_suffix(".cdi3.json")
    if cdi3_path.exists():
        params.update(_extract_params_from_cdi3(cdi3_path))
    return params


def load_model_lip_sync_profile(
    *,
    model_dir: str | Path,
    available_params: set[str] | tuple[str, ...] | list[str],
    override_filename: str = "lip_sync_profile.json",
) -> ModelLipSyncProfile:
    override_path = Path(model_dir) / override_filename
    override_payload: dict = {}
    if override_path.exists():
        try:
            override_payload = json.loads(override_path.read_text(encoding="utf-8-sig"))
        except Exception:
            override_payload = {}
    return build_model_lip_sync_profile_from_params(
        available_params,
        override_data=override_payload,
    )


def load_model_lip_sync_profile_for_model_json(
    model_json_path: str | Path | None = None,
    *,
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> ModelLipSyncProfile:
    raw_model_path = str(model_json_path or "").strip() or str(
        (settings_source or {}).get("model_json_path", DEFAULT_MODEL_JSON_PATH)
    ).strip() or DEFAULT_MODEL_JSON_PATH
    resolved_model_path = resolve_runtime_resource_path(
        raw_model_path,
        bundle_root=Path(base_path) if base_path is not None else get_bundle_root(),
    )
    available_params = extract_available_model_params(resolved_model_path)
    return load_model_lip_sync_profile(
        model_dir=resolved_model_path.parent,
        available_params=available_params,
    )
