"""공개 캐릭터 상태는 PC 렌더러 확인 및 현재 실행 세대에만 종속된다."""

import json

import pytest

from src.core.companion.character_assets import build_bundle
from src.core.companion.character_state import CharacterState, CharacterStateError
from tests.test_companion_character_assets import synthetic_model
from tests.companion_helpers import sample_id


CATALOG = [{"id": "ParamAccent", "min": -1.0, "max": 1.0, "default": 0.0}]


def state_with_bundle(tmp_path):
    state = CharacterState()
    bundle = build_bundle(synthetic_model(tmp_path))
    state.select(
        sample_id(41),
        bundle,
        {"enable_head_pat": True, "synthetic_private_setting": "exclude"},
        {"ParamAccent": 0.4},
    )
    return state, bundle


def test_only_matching_pc_catalog_can_make_public_character_ready(tmp_path):
    state, bundle = state_with_bundle(tmp_path)
    assert state.snapshot()["status"] == "loading"
    assert state.snapshot()["assets"] == []
    assert not state.accept_catalog(
        sample_id(42), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"]
    )
    assert not state.accept_catalog(
        sample_id(41), "a" * 64, CATALOG, ["normal"], ["nod"]
    )
    assert state.accept_catalog(
        sample_id(41), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"]
    )
    snapshot = state.snapshot()
    assert snapshot["status"] == "ready"
    assert snapshot["parameter_catalog"] == CATALOG
    assert snapshot["parameters"] == {"ParamAccent": 0.4}
    assert "synthetic_private_setting" not in snapshot["settings"]
    assert snapshot["expression_ids"] == ["bright", "normal"]
    assert "modelPath" not in json.dumps(snapshot)


@pytest.mark.parametrize(
    "catalog",
    [
        [{"id": "ParamAccent", "min": 2, "max": 1, "default": 1}],
        [{"id": "ParamAccent", "min": 0, "max": 1, "default": 2}],
        [{"id": "ParamAccent", "min": float("nan"), "max": 1, "default": 0}],
        CATALOG * 2,
        CATALOG * 257,
    ],
)
def test_invalid_or_duplicate_catalog_is_not_published(tmp_path, catalog):
    state, bundle = state_with_bundle(tmp_path)
    with pytest.raises(CharacterStateError):
        state.accept_catalog(
            sample_id(41), bundle.model_version, catalog, ["normal"], ["nod"]
        )
    assert state.snapshot()["status"] == "loading"


def test_snapshot_captures_current_base_and_high_water_without_replaying_actions(
    tmp_path,
):
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(
        sample_id(41), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"]
    )
    settings_revision = state.settings_revision
    expression = state.action("expression", "bright", 100)
    gesture = state.action("gesture", "nod", 600)
    assert expression["action_seq"] + 1 == gesture["action_seq"]
    capture = state.capture()
    snapshot = json.loads(capture.body)
    assert snapshot["action_seq"] == gesture["action_seq"]
    assert snapshot["default_expression"] == "bright"
    assert "actions" not in snapshot
    assert snapshot["settings_revision"] == settings_revision
    state.action("expression", "normal", 0)
    assert json.loads(capture.body)["default_expression"] == "bright"
    assert state.action("gesture", "not-listed", 1) is None


def test_replacement_invalidates_old_catalog_and_unsupported_has_no_assets(tmp_path):
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(
        sample_id(41), bundle.model_version, CATALOG, ["normal"], ["nod"]
    )
    revision = state.state_revision
    state.unavailable("unsupported")
    snapshot = state.snapshot()
    assert snapshot["state_revision"] > revision
    assert snapshot["model_version"] is None and snapshot["assets"] == []
    assert snapshot["model_id"] is None
    assert not state.accept_catalog(
        sample_id(41), bundle.model_version, CATALOG, ["normal"], ["nod"]
    )
    assert state.action("gesture", "nod", 500) is None
