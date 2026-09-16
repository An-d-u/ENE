"""PC 편집 기준과 원격 확정값이 충돌할 때 덮어쓰기·거짓 저장 완료를 막는다."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.companion.character_bridge import CompanionCharacterBridge
from src.ui.settings_dialog_values import SettingsDialogValuesMixin
from tests.test_companion_bridge_transcript import bridge as synthetic_bridge  # noqa: F401
from tests.test_companion_character_settings_storage import settings  # noqa: F401
from tests.test_companion_character_state import CATALOG, state_with_bundle
from tests.companion_helpers import sample_id


@pytest.fixture
def settings_bridge(request, tmp_path, monkeypatch):
    owner = request.getfixturevalue("synthetic_bridge")
    store = request.getfixturevalue("settings")
    store.config["model_json_path"] = "synthetic/model"
    owner.settings = store
    character = CompanionCharacterBridge(owner)
    owner._companion_character = character
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(sample_id(41), bundle.model_version, CATALOG, ["normal", "bright"], ["nod"])
    character.state = state
    store.config.update(state.settings)
    character._active = True
    events = []
    monkeypatch.setattr(character, "_publish", lambda kind, fields: events.append((kind, fields)))
    return character, store, events


def test_pc_dirty_keys_merge_different_remote_changes(settings_bridge):
    character, store, events = settings_bridge
    baseline = character.settings_baseline()
    store.commit_character_settings({"enable_head_pat": False})
    character.state.commit_settings({**character.state.settings, "enable_head_pat": False}, character.state.parameters)
    values = {**baseline["settings"], "idle_motion_strength": 1.3, "window_x": 321}
    answer = character.save_local_settings(values, baseline)
    assert answer["status"] == "accepted"
    assert not store.config["enable_head_pat"] and store.config["idle_motion_strength"] == 1.3
    assert store.config["window_x"] == 123
    assert answer["settings"]["enable_head_pat"] is False
    assert events[-1][0] == "character_changed"


def test_pc_same_dirty_key_conflicts_and_preserves_current_value(settings_bridge):
    character, store, events = settings_bridge
    baseline = character.settings_baseline()
    store.commit_character_settings({"idle_motion_strength": 1.2})
    before = deepcopy(store.config)
    answer = character.save_local_settings({**baseline["settings"], "idle_motion_strength": 1.4}, baseline)
    assert answer["status"] == "conflict"
    assert answer["conflicts"] == {"idle_motion_strength": 1.2}
    assert store.config == before and events == []


def test_save_failure_does_not_change_public_or_local_settings(settings_bridge, monkeypatch):
    character, store, events = settings_bridge
    before, snapshot = deepcopy(store.config), character.state.snapshot()
    def fail(*args, **kwargs):
        raise OSError("합성 저장 실패")
    monkeypatch.setattr(store, "commit_character_settings", fail)
    answer = character.save_local_settings({"enable_head_pat": False}, character.settings_baseline())
    assert answer["status"] == "rejected"
    assert store.config == before and character.state.snapshot() == snapshot and not events


def test_old_model_window_cannot_save_into_current_model(settings_bridge):
    character, store, _ = settings_bridge
    baseline = character.settings_baseline()
    store.config["model_json_path"] = "synthetic/other"
    assert character.save_local_settings({"enable_head_pat": False}, baseline)["status"] == "conflict"


def test_preview_never_changes_public_revision_and_cancel_uses_current_confirmation(settings_bridge):
    character, store, _ = settings_bridge
    before = character.state.snapshot()
    character.preview(True)
    assert character.state.snapshot() == before
    store.commit_character_settings({"enable_head_pat": False})
    assert character.settings_baseline()["settings"]["enable_head_pat"] is False
    character.preview(False)
    assert character.state.state_revision == before["state_revision"]


def test_actual_qt_admission_rejects_old_context_before_mutation(settings_bridge, monkeypatch):
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter
    from src.core.companion.protocol import decode_message, encode_message
    from tests.test_companion_adapter import context, run_adapter

    character, store, events = settings_bridge
    owner = character.owner
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)
    calls = []
    commit = store.commit_character_settings

    def checked_commit(*args, **kwargs):
        assert QThread.currentThread() == owner.thread()
        calls.append(1)
        return commit(*args, **kwargs)

    monkeypatch.setattr(store, "commit_character_settings", checked_commit)
    patch = {"protocol_version": 1, "type": "character_settings_patch", "registration_generation": 1,
             "server_epoch": owner.head().server_epoch, "connection_generation": sample_id(1),
             "command_id": sample_id(83), "model_version": character.state.bundle.model_version,
             "expected_revision": character.state.settings_revision, "changes": {"enable_head_pat": False}, "parameters": {}}
    message = decode_message(encode_message(patch))

    async def scenario():
        await adapter.call("connect", context())
        for stale in (context(connection=2), context(registration=2)):
            with pytest.raises(AdapterError):
                await adapter.call("extension", stale, message=message)
        assert not calls
        first = await adapter.call("extension", context(), message=message)
        assert first.to_dict()["status"] == "accepted"
        assert "model_key" not in encode_message(first)
        assert (await adapter.call("extension", context(), message=message)) == first
        assert len(calls) == 1
        await adapter.call("disconnect", context())
        await adapter.call("connect", context(connection=2))
        second = decode_message(encode_message({**patch, "connection_generation": sample_id(2)}))
        assert (await adapter.call("extension", context(connection=2), message=second)).to_dict()["status"] == "conflict"
        assert len(calls) == 1
        await adapter.call("block", context(connection=2))
        with pytest.raises(AdapterError, match="admission_blocked"):
            await adapter.call("extension", context(connection=2), message=second)

    run_adapter(QApplication.instance(), adapter, scenario)
    assert len(events) == 1
    adapter.disable()


class Dialog:
    def __init__(self, result):
        self._theme_color_edits = {}
        self._character_baseline = {"settings_revision": 1, "settings": {}}
        self._settings_save_handler = lambda values, baseline: result
        self._get_current_values = lambda: {"enable_head_pat": False}
        self._translated_text = lambda key, fallback, **kwargs: fallback
        self.messages, self.closed = [], False
        self.settings_changed = SimpleNamespace(emit=self.messages.append)
        self.close = lambda: setattr(self, "closed", True)


def test_dialog_marks_saved_and_closes_only_after_successful_commit(monkeypatch):
    notices = []
    monkeypatch.setattr("src.ui.settings_dialog_values.QMessageBox.warning", lambda *args: notices.append(args[-1]))
    failed = Dialog({"status": "rejected", "reason": "storage_failed"})
    SettingsDialogValuesMixin._save_settings(failed)
    assert not getattr(failed, "_saved", False) and not failed.closed and not failed.messages
    assert notices
    accepted = Dialog({"status": "accepted"})
    SettingsDialogValuesMixin._save_settings(accepted)
    assert accepted._saved and accepted.closed and len(accepted.messages) == 1


def test_dialog_conflict_keeps_user_edits_and_reports_current_shared_value(monkeypatch):
    notices = []
    monkeypatch.setattr("src.ui.settings_dialog_values.QMessageBox.warning", lambda *args: notices.append(args[-1]))
    current = {"settings_revision": 4, "settings": {"enable_head_pat": True}}
    dialog = Dialog({"status": "conflict", "baseline": current, "conflicts": {"enable_head_pat": True}})
    SettingsDialogValuesMixin._save_settings(dialog)
    assert not dialog.closed and not dialog.messages
    assert dialog._get_current_values() == {"enable_head_pat": False}
    assert dialog._character_baseline == current
    assert "enable_head_pat" in notices[-1]


def test_conflict_acknowledgement_rebases_only_conflicting_user_keys(monkeypatch):
    monkeypatch.setattr("src.ui.settings_dialog_values.QMessageBox.warning", lambda *args: None)
    current = {"settings_revision": 4, "settings": {"idle_motion_strength": 1.2, "enable_head_pat": False}}
    dialog = Dialog({"status": "conflict", "baseline": current, "conflicts": {"idle_motion_strength": 1.2}})
    dialog._character_baseline = {"settings_revision": 1, "settings": {"idle_motion_strength": 1.0, "enable_head_pat": True}}
    dialog._get_current_values = lambda: {"idle_motion_strength": 1.4, "enable_head_pat": True}
    SettingsDialogValuesMixin._save_settings(dialog)
    assert dialog._character_baseline["settings"] == {"idle_motion_strength": 1.2, "enable_head_pat": True}


def test_pc_same_model_cannot_store_unknown_expression(settings_bridge):
    character, store, _ = settings_bridge
    before = deepcopy(store.config)
    answer = character.save_local_settings({"head_pat_active_emotion_custom": "missing"}, character.settings_baseline())
    assert answer["status"] == "rejected" and store.config == before


def test_app_rejects_shared_conflict_before_touching_other_settings():
    from tests.test_ui_i18n_smoke import _load_app_class
    application = _load_app_class()
    answer = {"status": "conflict", "reason": "revision_conflict"}
    bridge = SimpleNamespace(_companion_save_local_settings=lambda values, baseline: answer)
    app = SimpleNamespace(overlay_window=SimpleNamespace(bridge=bridge))
    assert application._on_settings_changed(app, {"enable_head_pat": False}, baseline={}) == answer


def test_overlay_merge_uses_current_shared_values_not_old_whole_dict(settings_bridge):
    character, store, _ = settings_bridge
    owner = character.owner
    store.commit_character_settings({"enable_head_pat": False})
    original = deepcopy(store.config["live2d_parameter_overrides"])
    merged = owner._companion_confirmed_settings({"enable_head_pat": True, "window_x": 321, "live2d_parameter_overrides": {}})
    assert merged["enable_head_pat"] is False and merged["window_x"] == 321
    assert merged["live2d_parameter_overrides"] == original


def test_reusing_same_selection_does_not_restart_asset_worker_or_undo_current_settings(settings_bridge, monkeypatch):
    character, store, _ = settings_bridge
    character._active = False
    generation = character.select("synthetic/model", ["normal"], character.state.settings, {})
    calls = []
    monkeypatch.setattr(character, "_invalidate", lambda status: calls.append(status))
    store.commit_character_settings({"enable_head_pat": False})
    character.save_local_settings({"idle_motion_strength": 1.3}, character.settings_baseline())
    revision = character.state.state_revision
    assert character.select("synthetic/model", ["normal"], store.config, {}, reuse=True) == generation
    assert character.state.state_revision == revision and calls == []


def test_remote_commit_preserves_pc_favorites_and_duplicate_does_not_reapply(settings_bridge):
    character, store, events = settings_bridge
    patch = {"command_id": sample_id(81), "model_version": character.state.bundle.model_version,
             "expected_revision": character.state.settings_revision,
             "changes": {"enable_head_pat": False}, "parameters": {"ParamAccent": 0.8}}
    first = character.save_remote_settings("synthetic-connection", patch)
    assert first["status"] == "accepted"
    assert character.save_remote_settings("synthetic-connection", patch) == first
    assert len(events) == 1
    selected = store.config["live2d_parameter_overrides"]["synthetic/model"]
    assert selected["favorites"] == ["ParamKeep"] and selected["values"]["ParamAccent"] == .8
    assert selected["values"]["ParamKeep"] == .3
    assert character.state.parameters["ParamAccent"] == .8


def test_remote_confirmation_does_not_override_pc_preview(settings_bridge, monkeypatch):
    character, store, _ = settings_bridge
    applied = []
    monkeypatch.setattr(character, "_apply_confirmed_to_pc", lambda: applied.append(1), raising=False)
    character.preview(True)
    patch = {"command_id": sample_id(82), "model_version": character.state.bundle.model_version,
             "expected_revision": character.state.settings_revision,
             "changes": {"enable_head_pat": False}, "parameters": {}}
    assert character.save_remote_settings("synthetic-connection", patch)["status"] == "accepted"
    assert not store.config["enable_head_pat"] and applied == []


def test_worker_result_uses_latest_committed_settings_not_selection_copy(settings_bridge, monkeypatch):
    character, store, _ = settings_bridge
    bundle = character.state.bundle
    monkeypatch.setattr(character, "_builder", lambda *args, **kwargs: bundle)
    generation = character.select("synthetic/model", ["normal", "bright"], character.state.settings, {"ParamAccent": .4})
    character._thread.join(timeout=2)
    assert not character._thread.is_alive()
    assert character.save_local_settings({"enable_head_pat": False}, character.settings_baseline())["status"] == "accepted"
    character._poll()
    character.catalog({"generation": generation, "model_version": bundle.model_version,
                       "parameters": CATALOG, "expressions": ["normal", "bright"], "gestures": ["nod"]})
    assert character.state.status == "ready" and not character.state.settings["enable_head_pat"]
    assert character.state.parameters == {"ParamAccent": .4}


def test_parameter_save_uses_explicit_baseline_and_reports_success_after_atomic_write(settings_bridge):
    import json
    character, store, events = settings_bridge
    owner = character.owner
    baseline = json.loads(owner.get_live2d_parameter_edit_snapshot("synthetic/model"))
    desired = deepcopy(baseline["payload"])
    desired["values"]["ParamAccent"] = .7
    answer = json.loads(owner.commit_live2d_parameter_overrides("synthetic/model", json.dumps(desired), json.dumps(baseline)))
    assert answer["status"] == "accepted"
    assert answer["baseline"]["payload"]["values"]["ParamAccent"] == .7
    assert store.config["live2d_parameter_overrides"]["synthetic/model"]["favorites"] == ["ParamKeep"]
    assert character.state.parameters["ParamAccent"] == .7 and events[-1][0] == "character_changed"


def test_parameter_conflict_does_not_clear_edits_or_overwrite_remote_value(settings_bridge):
    import json
    character, store, _ = settings_bridge
    owner = character.owner
    baseline = json.loads(owner.get_live2d_parameter_edit_snapshot("synthetic/model"))
    store.commit_character_settings({}, model_key="synthetic/model", parameters={"ParamAccent": .6})
    desired = deepcopy(baseline["payload"])
    desired["values"]["ParamAccent"] = .8
    result = json.loads(owner.commit_live2d_parameter_overrides("synthetic/model", json.dumps(desired), json.dumps(baseline)))
    assert result["status"] == "conflict" and result["conflicts"] == {"ParamAccent": .6}
    assert store.config["live2d_parameter_overrides"]["synthetic/model"]["values"]["ParamAccent"] == .6


def test_parameter_save_merges_other_changed_keys_without_resetting_favorites(settings_bridge):
    import json
    character, store, _ = settings_bridge
    character.state.catalog.append({"id": "ParamKeep", "min": 0, "max": 1, "default": 0})
    owner = character.owner
    baseline = json.loads(owner.get_live2d_parameter_edit_snapshot("synthetic/model"))
    store.commit_character_settings({}, model_key="synthetic/model", parameters={"ParamKeep": .9})
    desired = deepcopy(baseline["payload"])
    desired["values"]["ParamAccent"] = .8
    result = json.loads(owner.commit_live2d_parameter_overrides("synthetic/model", json.dumps(desired), json.dumps(baseline)))
    assert result["status"] == "accepted"
    assert result["baseline"]["payload"]["values"] == {"ParamAccent": .8, "ParamKeep": .9}


def test_parameter_write_failure_and_old_model_return_rejection(settings_bridge, monkeypatch):
    import json
    character, store, _ = settings_bridge
    owner = character.owner
    baseline = json.loads(owner.get_live2d_parameter_edit_snapshot("synthetic/model"))
    desired = deepcopy(baseline["payload"])
    desired["values"]["ParamAccent"] = .8
    before = deepcopy(store.config)
    def fail(*args):
        raise OSError("합성 파라미터 저장 실패")
    monkeypatch.setattr(store, "commit_live2d_parameter_overrides", fail, raising=False)
    answer = json.loads(owner.commit_live2d_parameter_overrides("synthetic/model", json.dumps(desired), json.dumps(baseline)))
    assert answer["status"] == "rejected" and answer["reason"] == "storage_failed"
    assert store.config == before
    store.config["model_json_path"] = "synthetic/other"
    answer = json.loads(owner.commit_live2d_parameter_overrides("synthetic/model", json.dumps(desired), json.dumps(baseline)))
    assert answer["status"] == "conflict" and answer["reason"] == "model_changed"
