"""실제 Qt 브리지의 합성 쓰다듬기만 기존 기록 경로에 전달한다."""

# pytest가 가져온 fixture 이름을 테스트 인자로 주입한다.
# ruff: noqa: F811

import json
from types import SimpleNamespace

from tests.test_companion_settings_conflict_ui import settings_bridge  # noqa: F401
from tests.test_companion_settings_conflict_ui import synthetic_bridge, settings  # noqa: F401
from tests.companion_helpers import sample_id


def pc_input(character, phase="start", seq=0, **changes):
    generation = character.settings_baseline()["generation"]
    return json.dumps({"model_generation": generation, "interaction_id": sample_id(300),
                       "phase": phase, "seq": seq, "intensity": .4, **changes})


def test_pc_requires_accepted_start_and_legacy_count_slot_cannot_bypass(settings_bridge, monkeypatch):
    character, _, _ = settings_bridge
    owner = character.owner
    counted = []
    owner.calendar_manager = SimpleNamespace(increment_head_pat_count=lambda: counted.append("legacy"))
    monkeypatch.setattr(owner, "_record_confirmed_head_pat", lambda: counted.append(1), raising=False)
    owner.increment_head_pat_count_from_js()
    assert not counted
    answer = json.loads(owner.submit_head_pat_input(pc_input(character)))
    assert answer["phase"] == "accepted"
    ended = pc_input(character, "end", 1)
    assert json.loads(owner.submit_head_pat_input(ended))["phase"] == "ended"
    owner.submit_head_pat_input(ended)
    assert counted == [1]
    owner._companion_head_pat.close()


def test_phone_and_pc_share_one_coordinator_and_phone_disconnect_cancels_only_phone(settings_bridge, monkeypatch):
    character, _, _ = settings_bridge
    owner = character.owner
    counted = []
    monkeypatch.setattr(owner, "_record_confirmed_head_pat", lambda: counted.append(1), raising=False)
    pat = owner._ensure_companion_head_pat()
    phone = {"model_version": character.state.bundle.model_version, "interaction_id": sample_id(301),
             "interaction_no": 1, "phase": "start", "seq": 0, "intensity": .3}
    assert pat.phone(sample_id(2), phone)["phase"] == "accepted"
    assert json.loads(owner.submit_head_pat_input(pc_input(character)))["reason"] == "busy"
    owner._companion_connection_closed()
    assert pat.coordinator.active is None and not counted
    owner.submit_head_pat_input(pc_input(character, interaction_id=sample_id(302)))
    owner._companion_connection_closed()
    assert pat.coordinator.active.source == "pc"
    pat.close()


def test_model_change_preview_and_invalid_pc_input_do_not_count(settings_bridge, monkeypatch):
    character, _, _ = settings_bridge
    owner = character.owner
    counted = []
    monkeypatch.setattr(owner, "_record_confirmed_head_pat", lambda: counted.append(1), raising=False)
    old = pc_input(character)
    owner.submit_head_pat_input(old)
    character.preview(True)
    assert owner._companion_head_pat.coordinator.active is None
    assert json.loads(owner.submit_head_pat_input(old))["phase"] == "rejected"
    assert json.loads(owner.submit_head_pat_input("x" * 2049))["phase"] == "rejected"
    character.preview(False)
    assert json.loads(owner.submit_head_pat_input(pc_input(character, model_generation=sample_id(999))))["phase"] == "rejected"
    assert not counted
    owner._companion_head_pat.close()


def test_pc_only_mode_keeps_local_count_without_sending_private_model_identity(settings_bridge, monkeypatch):
    character, _, events = settings_bridge
    owner = character.owner
    counted = []
    monkeypatch.setattr(owner, "_record_confirmed_head_pat", lambda: counted.append(1), raising=False)
    character._active = False
    character.select(None, (), character.state.settings, {})
    events.clear()
    assert json.loads(owner.submit_head_pat_input(pc_input(character)))["phase"] == "accepted"
    owner.submit_head_pat_input(pc_input(character, "end", 1))
    assert counted == [1] and not events
    owner._companion_head_pat.close()


def test_old_phone_cancellation_is_not_broadcast_to_replacement_connection(settings_bridge, monkeypatch):
    character, _, events = settings_bridge
    owner = character.owner
    current = [sample_id(2)]
    owner._companion_adapter = SimpleNamespace(is_current_connection=lambda connection: connection == current[0])
    pat = owner._ensure_companion_head_pat()
    fields = {"model_version": character.state.bundle.model_version, "interaction_id": sample_id(330),
              "interaction_no": 250, "phase": "start", "seq": 0, "intensity": .3}
    assert pat.phone(sample_id(2), fields)["phase"] == "accepted"
    events.clear()
    current[0] = sample_id(3)
    pat.phone(sample_id(3), {**fields, "interaction_id": sample_id(331), "interaction_no": 1})
    assert [item[1]["phase"] for item in events] == ["accepted"]
    assert events[0][1]["interaction_no"] == 1
    pat.close()
