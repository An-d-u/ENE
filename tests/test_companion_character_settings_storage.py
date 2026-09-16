"""합성 config만 원자적으로 바꾸고 비밀 파일과 모델별 로컬 값을 보존한다."""

from copy import deepcopy
import json

import pytest

from src.core.settings import Settings
from src.core import app_paths


@pytest.fixture
def settings(tmp_path):
    # 생성자의 사용자 저장소 탐색을 피하고 테스트 전용 메모리·경로만 주입한다.
    value = Settings.__new__(Settings)
    value.config_path = tmp_path / "synthetic-config.json"
    value.secret_path = tmp_path / "synthetic-private-sentinel.bin"
    value.config = {"enable_head_pat": True, "window_x": 123, "live2d_parameter_overrides": {
        "synthetic/model": {"values": {"ParamAccent": 0.2, "ParamKeep": 0.3}, "favorites": ["ParamKeep"]},
        "synthetic/other": {"values": {"ParamOther": 0.8}, "favorites": []},
    }}
    value.secret_config = {"synthetic_secret": "sentinel-only"}
    app_paths.save_json_data_atomic(value.config_path, value.config)
    value.secret_path.write_bytes(b"synthetic-private-sentinel")
    return value


def test_commit_merges_current_config_and_preserves_other_models_and_favorites(settings):
    original = deepcopy(settings.config)
    settings.commit_character_settings({"enable_head_pat": False}, model_key="synthetic/model", parameters={"ParamAccent": None, "ParamNew": 0.4})
    assert settings.config["window_x"] == 123 and not settings.config["enable_head_pat"]
    models = settings.config["live2d_parameter_overrides"]
    assert models["synthetic/model"] == {"values": {"ParamKeep": 0.3, "ParamNew": 0.4}, "favorites": ["ParamKeep"]}
    assert models["synthetic/other"] == original["live2d_parameter_overrides"]["synthetic/other"]
    raw = settings.config_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and json.loads(raw) == settings.config
    assert settings.secret_path.read_bytes() == b"synthetic-private-sentinel"
    assert settings.secret_config == {"synthetic_secret": "sentinel-only"}


def test_replace_failure_keeps_file_memory_and_secret_unchanged(settings, monkeypatch):
    original, raw = deepcopy(settings.config), settings.config_path.read_bytes()
    def fail(*_):
        raise OSError("합성 교체 실패")
    monkeypatch.setattr(app_paths, "_replace_file_atomic_durable", fail)
    with pytest.raises(OSError):
        settings.commit_character_settings({"enable_head_pat": False}, model_key="synthetic/model", parameters={"ParamAccent": 1.0})
    assert settings.config == original and settings.config_path.read_bytes() == raw
    assert settings.secret_path.read_bytes() == b"synthetic-private-sentinel"
    assert not list(settings.config_path.parent.glob(".synthetic-config.json.*.tmp"))


@pytest.mark.parametrize("changes,parameters", [
    ({"window_x": 1}, {}), ({"enable_head_pat": 1}, {}),
    ({}, {"ParamAccent": float("nan")}), ({}, {"__proto__": 1}),
    ({}, {"ParamAccent": 10 ** 400}),
])
def test_storage_entry_rejects_non_shared_or_invalid_changes(settings, changes, parameters):
    original, raw = deepcopy(settings.config), settings.config_path.read_bytes()
    with pytest.raises(ValueError):
        settings.commit_character_settings(changes, model_key="synthetic/model", parameters=parameters)
    assert settings.config == original and settings.config_path.read_bytes() == raw


def test_coordinator_and_atomic_file_keep_same_revision_on_write_failure(settings, tmp_path, monkeypatch):
    from src.core.companion.character_controls import CharacterControls
    from tests.companion_helpers import sample_id
    from tests.test_companion_character_state import CATALOG, state_with_bundle

    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(sample_id(41), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"])
    control = CharacterControls(state, lambda changes, parameters: settings.commit_character_settings(
        changes, model_key="synthetic/model", parameters=parameters))
    original, raw, snapshot = deepcopy(settings.config), settings.config_path.read_bytes(), state.snapshot()
    def fail(*_):
        raise OSError("합성 동기화 실패")
    monkeypatch.setattr(app_paths.os, "fsync", fail)
    result = control.patch("synthetic-connection", command_id=sample_id(1), model_version=bundle.model_version,
                           expected_revision=state.settings_revision, changes={"enable_head_pat": False}, parameters={})
    assert result["status"] == "rejected" and result["reason"] == "storage_failed"
    assert settings.config == original and settings.config_path.read_bytes() == raw
    assert state.snapshot() == snapshot
