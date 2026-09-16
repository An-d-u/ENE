"""공유 설정은 현재 모델·revision·명령 내용이 일치할 때만 한 번 저장한다."""

from copy import deepcopy

import pytest

from src.core.companion.character_controls import CharacterControls
from src.core.companion.extension_protocol import BOOL_SETTINGS, INT_SETTINGS, NUMBER_SETTINGS
from tests.companion_helpers import sample_id
from tests.test_companion_character_state import CATALOG, state_with_bundle


@pytest.fixture
def controls(tmp_path):
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(sample_id(41), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"])
    saved = []
    control = CharacterControls(state, lambda changes, parameters: saved.append((deepcopy(changes), deepcopy(parameters))))
    return control, state, saved


def patch(control, state, *, number=1, revision=None, model=None, changes=None, parameters=None):
    return control.patch("synthetic-connection", command_id=sample_id(number),
                         model_version=model or state.bundle.model_version,
                         expected_revision=state.settings_revision if revision is None else revision,
                         changes=changes or {}, parameters=parameters or {})


def test_current_changes_commit_once_and_increase_both_revisions(controls):
    control, state, saved = controls
    old = state.snapshot()
    result = patch(control, state, changes={"enable_head_pat": False, "idle_motion_strength": 2.0}, parameters={"ParamAccent": None})
    assert result["status"] == "accepted"
    assert result["settings_revision"] == old["settings_revision"] + 1
    assert state.state_revision == old["state_revision"] + 1
    assert state.parameters == {} and not state.settings["enable_head_pat"]
    assert saved == [({"enable_head_pat": False, "idle_motion_strength": 2.0}, {"ParamAccent": None})]


@pytest.mark.parametrize("changes,parameters", [
    ({"unknown": True}, {}), ({"enable_head_pat": 1}, {}),
    ({"idle_motion_strength": 0.19}, {}), ({"idle_motion_speed": 2.01}, {}),
    ({"head_pat_fade_in_ms": 50.0}, {}), ({"head_pat_end_emotion_duration_sec": 31}, {}),
    ({"head_pat_active_emotion_custom": "missing"}, {}),
    ({"expressive_motion_strength": float("nan")}, {}),
    ({}, {"Missing": None}), ({}, {"ParamAccent": 1.01}),
    ({}, {"ParamAccent": True}), ({}, {"ParamAccent": float("inf")}),
    ({}, {str(n): 0 for n in range(257)}),
])
def test_invalid_settings_or_parameters_change_nothing(controls, changes, parameters):
    control, state, saved = controls
    before = state.snapshot()
    assert patch(control, state, changes=changes, parameters=parameters)["status"] == "rejected"
    assert state.snapshot() == before and saved == []


def test_boundaries_and_current_expression_ids_are_accepted(controls):
    control, state, _ = controls
    result = patch(control, state, changes={
        "idle_motion_strength": 0.2, "idle_motion_speed": 0.5,
        "expressive_motion_strength": 2.5, "expressive_motion_speed": 0.4,
        "expressive_motion_speech_boost": 0.0, "synthetic_gesture_scale": 3.0,
        "head_pat_fade_in_ms": 50, "head_pat_fade_out_ms": 1200,
        "head_pat_end_emotion_duration_sec": 30, "head_pat_active_emotion_custom": "bright",
        "head_pat_end_emotion_custom": "", "idle_synthetic_gesture_frequency": "high",
    }, parameters={"ParamAccent": -1.0})
    assert result["status"] == "accepted"


def test_old_revision_or_model_conflicts_without_saving(controls):
    control, state, saved = controls
    assert patch(control, state, revision=state.settings_revision - 1)["status"] == "conflict"
    assert patch(control, state, number=2, model="b" * 64)["status"] == "conflict"
    assert saved == []


def test_duplicate_is_checked_before_revision_and_different_body_conflicts(controls):
    control, state, saved = controls
    revision = state.settings_revision
    first = patch(control, state, revision=revision, changes={"enable_head_pat": False})
    assert patch(control, state, revision=revision, changes={"enable_head_pat": False}) == first
    assert patch(control, state, revision=revision, changes={"enable_head_pat": True})["status"] == "conflict"
    assert len(saved) == 1


def test_evicted_command_cannot_reapply_because_even_noop_increases_revision(controls):
    control, state, saved = controls
    revision = state.settings_revision
    for number in range(1, 259):
        assert patch(control, state, number=number)["status"] == "accepted"
    assert control.cached_commands == 256
    assert patch(control, state, revision=revision)["status"] == "conflict"
    assert len(saved) == 258


def test_storage_failure_keeps_state_and_failure_result_does_not_retry(controls):
    control, state, _ = controls
    calls = []
    def fail(changes, parameters):
        calls.append(1)
        raise OSError("합성 저장 실패")
    control.commit = fail
    before = state.snapshot()
    result = patch(control, state, changes={"enable_head_pat": False})
    assert result["status"] == "rejected" and result["reason"] == "storage_failed"
    assert patch(control, state, changes={"enable_head_pat": False}) == result
    assert state.snapshot() == before and len(calls) == 1


def test_unavailable_model_and_stale_connection_cache_do_not_grow(controls):
    control, state, saved = controls
    model = state.bundle.model_version
    state.unavailable()
    result = patch(control, state, model=model)
    assert result["status"] == "rejected" and not saved
    control.disconnected()
    assert control.cached_commands == 0


@pytest.mark.parametrize("key,limits", sorted({**INT_SETTINGS, **NUMBER_SETTINGS}.items()))
def test_every_numeric_setting_accepts_both_limits_and_rejects_outside(controls, key, limits):
    control, state, saved = controls
    low, high = limits
    for number, value in enumerate((low, high), 1):
        assert patch(control, state, number=number, changes={key: value})["status"] == "accepted"
    for number, value in enumerate((low - 1, high + 1), 3):
        assert patch(control, state, number=number, changes={key: value})["status"] == "rejected"
    assert len(saved) == 2


@pytest.mark.parametrize("key", sorted(BOOL_SETTINGS))
def test_every_switch_requires_an_actual_boolean(controls, key):
    control, state, saved = controls
    for number, value in enumerate((True, False), 1):
        assert patch(control, state, number=number, changes={key: value})["status"] == "accepted"
    assert patch(control, state, number=3, changes={key: "false"})["status"] == "rejected"
    assert len(saved) == 2


def test_maximum_catalog_with_multibyte_identifiers_does_not_exceed_command_budget(controls):
    control, state, _ = controls
    catalog = [{"id": f"{n:03d}" + "가" * 41, "min": 0, "max": 1, "default": 0} for n in range(256)]
    state.accept_catalog(state.generation, state.bundle.model_version, catalog, state.expressions, state.gestures)
    result = patch(control, state, parameters={item["id"]: 0.5 for item in catalog})
    assert result["status"] == "accepted"
    assert len(state.parameters) == 256
