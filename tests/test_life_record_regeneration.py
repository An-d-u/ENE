from __future__ import annotations

from datetime import datetime
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.ai.life_record_manager import LifeRecordManager
from src.ai.life_record_types import (
    create_life_record,
    parse_and_validate_life_record_output,
    stable_life_record_id,
)
from src.ai.response_protocol import OneShotTokenUsage, ResponseStatus
from src.core.bridge import WebBridge
from src.core.bridge_mixins.life_records import LifeRecordBridgeMixin
from src.core.bridge_state import LifeRecordBridgeState
from src.core.bridge_workers import LifeRecordWorkerResult
from src.core.local_time import resolve_local_time_context


SEOUL = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


class _Signal:
    def __init__(self, events: list[tuple], name: str) -> None:
        self.events = events
        self.name = name
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        self.events.append((self.name, *args))
        for callback in tuple(self.callbacks):
            callback(*args)


class _Worker:
    instances = []

    def __init__(self, llm_client, request) -> None:
        self.llm_client = llm_client
        self.request = request
        self.result_ready = _Signal([], "result")
        self.error_occurred = _Signal([], "error")
        self.finished = _Signal([], "finished")
        self.started = False
        self.interrupted = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


class _Profile:
    def export_life_record_profile(self, max_facts=10):
        return {
            "ene_identity": {"identity": ("현재 합성 기록 안내자",)},
            "relationship_tone": ("현재 합성 방문객을 차분히 맞이한다.",),
            "profile_facts": (
                {"category": "habit", "content": "현재 합성 온실을 둘러본다."},
            ),
        }


class _Bridge(LifeRecordBridgeMixin):
    def __init__(self, manager: LifeRecordManager) -> None:
        self.events = []
        self.life_record_state = LifeRecordBridgeState(
            auto_decision_completed=True,
            life_records_writable=True,
            time_context=resolve_local_time_context("UTC").context,
            view_timezone="UTC",
        )
        self.life_record_manager = manager
        self.llm_client = SimpleNamespace(life_record_manager=manager)
        self.ene_profile = _Profile()
        self.settings = {
            "ui_language": "en",
            "assistant_display_name": "Lumi",
            "user_address_name": "Traveler",
        }
        self.life_record_notice = _Signal(self.events, "notice")
        self.life_record_items_updated = _Signal(self.events, "items")
        self.request_pending_stage_changed = _Signal(self.events, "stage")
        self.request_pending_changed = _Signal(self.events, "pending")
        self.drains = 0

    def _load_life_world_for_gate(self) -> str:
        return "# Current synthetic village\n- Current greenhouse"

    def _defer_life_record_worker_finalization(self, callback) -> None:
        callback()

    def _drain_queues_after_worker_finished(self) -> None:
        self.drains += 1


def _record(start: datetime, end: datetime, activity: str, *, revision: int = 1):
    return create_life_record(
        id=stable_life_record_id(start, end),
        inactive_started_at=start,
        returned_at=end,
        created_at=end,
        updated_at=end,
        revision=revision,
        timezone=getattr(start.tzinfo, "key", "UTC"),
        inactive_start_source="heartbeat_recovery",
        mood_snapshot={
            "label": "calm",
            "valence": 0.1,
            "energy": 0.2,
            "bond": 0.3,
            "stress": 0.4,
            "short_term_mood": "steady",
        },
        entries=[
            {
                "started_at": start,
                "ended_at": end,
                "place": "합성 온실",
                "activity": activity,
            }
        ],
        ending_state={"place": "합성 온실", "summary": "합성 활동을 마쳤다."},
    )


def _seed(manager: LifeRecordManager):
    previous = _record(
        datetime(2099, 8, 5, 21, tzinfo=SEOUL),
        datetime(2099, 8, 5, 22, tzinfo=SEOUL),
        "PREVIOUS_SYNTHETIC_SENTINEL",
    )
    latest = _record(
        datetime(2099, 8, 6, 23, tzinfo=SEOUL),
        datetime(2099, 8, 7, 10, tzinfo=SEOUL),
        "TARGET_SYNTHETIC_SENTINEL",
    )
    assert manager.add(previous)
    assert manager.add(latest)
    return previous, latest


def _replacement_output(record):
    return parse_and_validate_life_record_output(
        json.dumps(
            {
                "entries": [
                    {
                        "started_at": record.inactive_started_at.isoformat(),
                        "ended_at": record.returned_at.isoformat(),
                        "place": "합성 광장",
                        "activity": "새 합성 일정을 보냈다.",
                    }
                ],
                "ending_state": {
                    "place": "합성 광장",
                    "summary": "새 합성 일정을 마쳤다.",
                },
            },
            ensure_ascii=False,
        ),
        inactive_started_at=record.inactive_started_at,
        returned_at=record.returned_at,
        timezone_name=record.timezone,
    )


def test_public_bridge_declares_regeneration_and_date_query_slots():
    assert hasattr(WebBridge, "request_life_records_for_date")
    assert hasattr(WebBridge, "regenerate_latest_life_record")


def test_date_query_uses_view_timezone_language_request_id_and_global_latest(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    bridge.settings["ui_language"] = "ja"
    bridge.life_record_state.view_timezone = "Asia/Seoul"

    bridge.request_life_records_for_date("2099-08-06", "synthetic-request-7")

    payload = json.loads([event[1] for event in bridge.events if event[0] == "items"][-1])
    assert payload["status"] == "ready"
    assert payload["request_id"] == "synthetic-request-7"
    assert payload["requested_date"] == "2099-08-06"
    assert payload["view_timezone"] == "Asia/Seoul"
    assert payload["language"] == "ja"
    assert [item["id"] for item in payload["records"]] == [latest.id]
    assert payload["latest_id"] == latest.id


def test_date_query_reports_safe_error_and_never_uses_stale_runtime_records(tmp_path):
    path = tmp_path / "life_records.json"
    manager = LifeRecordManager(path)
    _seed(manager)
    bridge = _Bridge(manager)
    original_events = list(bridge.events)
    original_bridge_manager = bridge.life_record_manager
    original_client_manager = bridge.llm_client.life_record_manager
    path.write_text("{broken", encoding="utf-8")

    bridge.request_life_records_for_date("2099-08-07", "synthetic-request-8")

    assert bridge.events == [*original_events, ("notice", "read_error")]
    assert bridge.life_record_manager is original_bridge_manager
    assert bridge.llm_client.life_record_manager is original_client_manager
    assert bridge.life_record_manager.latest() is not None


@pytest.mark.parametrize("iso_date", ["", "2099-02-30", "not-a-date"])
def test_date_query_rejects_invalid_date_with_safe_code(tmp_path, iso_date):
    bridge = _Bridge(LifeRecordManager(tmp_path / "life_records.json"))

    bridge.request_life_records_for_date(iso_date, "synthetic-request-invalid")

    assert bridge.events == [("notice", "invalid_date")]


def test_regeneration_uses_stored_interval_metadata_and_current_whitelist_context(
    monkeypatch, tmp_path
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)

    bridge.regenerate_latest_life_record(latest.id)

    worker = _Worker.instances[-1]
    assert worker.started is True
    assert bridge.life_record_state.phase == "manual_regenerating"
    assert bridge.life_record_state.worker is worker
    assert worker.request.inactive_started_at == latest.inactive_started_at
    assert worker.request.returned_at == latest.returned_at
    assert worker.request.timezone == latest.timezone
    assert worker.request.language == "en"
    assert "Current synthetic village" in worker.request.prompt
    assert "Current greenhouse" in worker.request.prompt
    assert "현재 합성 기록 안내자" in worker.request.prompt
    assert "현재 합성 온실을 둘러본다." in worker.request.prompt
    assert previous.entries[0].activity not in worker.request.prompt
    assert latest.entries[0].activity not in worker.request.prompt
    assert latest.inactive_started_at.isoformat() in worker.request.prompt
    assert "Asia/Seoul" in worker.request.prompt
    assert "English" in worker.request.prompt
    assert bridge.events == [
        ("stage", "life_record_regeneration"),
        ("pending", True),
    ]


def test_regeneration_preflight_read_error_keeps_runtime_context_object(tmp_path):
    path = tmp_path / "life_records.json"
    manager = LifeRecordManager(path)
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    path.write_text("{broken", encoding="utf-8")

    bridge.regenerate_latest_life_record(latest.id)

    assert bridge.life_record_manager is manager
    assert bridge.llm_client.life_record_manager is manager
    assert manager.latest() == latest
    assert bridge.events == [("notice", "read_error")]


@pytest.mark.parametrize("failing_signal", ["stage", "pending"])
def test_manual_start_signal_exception_rolls_back_and_drains_once(
    monkeypatch, tmp_path, failing_signal
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    original_emit = (
        bridge.request_pending_stage_changed.emit
        if failing_signal == "stage"
        else bridge.request_pending_changed.emit
    )

    def fail_after_emit(*args):
        original_emit(*args)
        raise RuntimeError("private-signal-detail")

    if failing_signal == "stage":
        monkeypatch.setattr(bridge.request_pending_stage_changed, "emit", fail_after_emit)
    else:
        monkeypatch.setattr(bridge.request_pending_changed, "emit", fail_after_emit)

    bridge.regenerate_latest_life_record(latest.id)

    assert bridge.life_record_state.phase == "idle"
    assert bridge.life_record_state.pending_request is None
    assert bridge.life_record_state.worker is None
    assert bridge.drains == 1
    assert ("pending", False) in bridge.events
    assert "private-signal-detail" not in repr(bridge.events)


def test_regeneration_uses_stored_dst_timezone_instead_of_current_view_timezone(
    monkeypatch, tmp_path
):
    new_york = ZoneInfo("America/New_York")
    target = _record(
        datetime(2026, 11, 1, 0, tzinfo=new_york),
        datetime(2026, 11, 1, 3, tzinfo=new_york),
        "SYNTHETIC_DST_TARGET",
    )
    manager = LifeRecordManager(tmp_path / "life_records.json")
    assert manager.add(target)
    bridge = _Bridge(manager)
    bridge.life_record_state.view_timezone = "Asia/Tokyo"
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)

    bridge.regenerate_latest_life_record(target.id)

    request = _Worker.instances[-1].request
    assert request.timezone == "America/New_York"
    assert "2026-11-01T00:00:00-04:00" in request.prompt
    assert "2026-11-01T03:00:00-05:00" in request.prompt
    assert "Asia/Tokyo" not in request.prompt


def test_regeneration_updated_at_advances_by_instant_across_dst_gap(
    monkeypatch, tmp_path
):
    new_york = ZoneInfo("America/New_York")
    target = _record(
        datetime(2099, 3, 8, 1, 0, tzinfo=new_york),
        datetime(2099, 3, 8, 1, 59, 59, tzinfo=new_york),
        "SYNTHETIC_DST_GAP_TARGET",
    )
    manager = LifeRecordManager(tmp_path / "life_records.json")
    assert manager.add(target)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)

    bridge.regenerate_latest_life_record(target.id)

    pending = bridge.life_record_state.pending_request
    assert pending.updated_at.isoformat() == "2099-03-08T03:00:00-04:00"


def test_success_replaces_same_id_after_finished_and_updates_runtime_and_panel(
    monkeypatch, tmp_path
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge.regenerate_latest_life_record(latest.id)
    worker = _Worker.instances[-1]
    bridge.settings["ui_language"] = "ja"
    result = LifeRecordWorkerResult(
        operation_id=bridge.life_record_state.operation_id,
        output=_replacement_output(latest),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(4, 5, 9),
        attempt_count=1,
    )

    worker.result_ready.emit(result.operation_id, result)
    assert manager.latest() == latest
    assert bridge.life_record_state.worker is worker
    worker.finished.emit()

    current = bridge.life_record_manager.latest()
    assert current.id == latest.id
    assert current.created_at == latest.created_at
    assert current.inactive_started_at == latest.inactive_started_at
    assert current.returned_at == latest.returned_at
    assert current.timezone == latest.timezone
    assert current.inactive_start_source == latest.inactive_start_source
    assert current.mood_snapshot == latest.mood_snapshot
    assert current.revision == latest.revision + 1
    assert current.entries[0].activity == "새 합성 일정을 보냈다."
    assert bridge.llm_client.life_record_manager.latest() == current
    payload = json.loads([event[1] for event in bridge.events if event[0] == "items"][-1])
    assert payload["record"]["id"] == latest.id
    assert payload["record"]["locale"] == "en"
    assert payload["affected_dates"] == ["2099-08-06", "2099-08-07"]
    assert payload["latest_id"] == latest.id
    assert bridge.life_record_state.phase == "idle"
    assert bridge.drains == 1
    assert bridge.events[-1] == ("pending", False)


@pytest.mark.parametrize("failure_step", ["serialization", "signal"])
def test_post_commit_panel_refresh_failure_keeps_committed_context_and_is_not_save_failure(
    monkeypatch, tmp_path, failure_step
):
    path = tmp_path / "life_records.json"
    manager = LifeRecordManager(path)
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge.regenerate_latest_life_record(latest.id)
    worker = _Worker.instances[-1]
    operation_id = bridge.life_record_state.operation_id
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_replacement_output(latest),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )
    if failure_step == "serialization":
        monkeypatch.setattr(
            LifeRecordManager,
            "to_public_dict",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("private-refresh-detail")
            ),
        )
    else:
        original_emit = bridge.life_record_items_updated.emit

        def fail_after_signal(payload):
            original_emit(payload)
            raise RuntimeError("private-refresh-detail")

        monkeypatch.setattr(bridge.life_record_items_updated, "emit", fail_after_signal)

    worker.result_ready.emit(operation_id, result)
    worker.finished.emit()

    committed = LifeRecordManager(path).latest()
    assert committed.id == latest.id
    assert committed.revision == latest.revision + 1
    assert bridge.life_record_manager.latest() == committed
    assert bridge.llm_client.life_record_manager.latest() == committed
    assert ("notice", "refresh_failed") in bridge.events
    assert ("notice", "save_failed") not in bridge.events
    assert "private-refresh-detail" not in repr(bridge.events)


@pytest.mark.parametrize(
    ("state_changes", "expected_code"),
    [
        ({"life_records_writable": False, "read_only_reason": "session_lease_unavailable"}, "session_lease_unavailable"),
        ({"life_records_writable": False, "read_only_reason": "session_tracker_degraded"}, "session_tracker_degraded"),
        ({"life_records_writable": False, "read_only_reason": "timezone_unavailable"}, "timezone_unavailable"),
        ({"phase": "normal_reply"}, "busy"),
        ({"phase": "auto_generating"}, "busy"),
    ],
)
def test_regeneration_rejects_read_only_and_busy_without_mutation(
    tmp_path, state_changes, expected_code
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    for key, value in state_changes.items():
        setattr(bridge.life_record_state, key, value)
    before = manager.records

    bridge.regenerate_latest_life_record(latest.id)

    assert manager.records == before
    assert bridge.events == [("notice", expected_code)]


def test_regeneration_rejects_past_and_missing_ids_without_mutation(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    previous, latest = _seed(manager)
    bridge = _Bridge(manager)

    bridge.regenerate_latest_life_record(previous.id)
    bridge.regenerate_latest_life_record("synthetic-missing-id")

    assert manager.latest() == latest
    assert bridge.events == [("notice", "not_latest"), ("notice", "not_latest")]


def test_duplicate_regeneration_is_rejected_without_starting_another_worker(
    monkeypatch, tmp_path
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)

    bridge.regenerate_latest_life_record(latest.id)
    bridge.regenerate_latest_life_record(latest.id)

    assert len(_Worker.instances) == 1
    assert bridge.life_record_state.phase == "manual_regenerating"
    assert bridge.events[-1] == ("notice", "busy")


def test_record_changed_while_worker_runs_rejects_stale_result(
    monkeypatch, tmp_path
):
    path = tmp_path / "life_records.json"
    manager = LifeRecordManager(path)
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge.regenerate_latest_life_record(latest.id)
    worker = _Worker.instances[-1]
    operation_id = bridge.life_record_state.operation_id
    external = LifeRecordManager(path)
    external.replace_latest(
        latest.id,
        _replacement_output(latest),
        latest.updated_at.replace(minute=latest.updated_at.minute + 1),
    )
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_replacement_output(latest),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )

    worker.result_ready.emit(operation_id, result)
    worker.finished.emit()

    assert bridge.life_record_manager.latest() == latest
    assert LifeRecordManager(path).latest() == external.latest()
    assert LifeRecordManager(path).latest().revision == latest.revision + 1
    assert ("notice", "save_failed") in bridge.events


@pytest.mark.parametrize("failure_kind", ["generation", "save", "cancel"])
def test_failure_cancel_and_save_error_keep_original_and_release_once(
    monkeypatch, tmp_path, failure_kind
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    original_bytes = (tmp_path / "life_records.json").read_bytes()
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge.regenerate_latest_life_record(latest.id)
    worker = _Worker.instances[-1]
    operation_id = bridge.life_record_state.operation_id
    if failure_kind == "generation":
        result = LifeRecordWorkerResult(
            operation_id=operation_id,
            output=None,
            status=None,
            token_usage=OneShotTokenUsage(None, None, None),
            attempt_count=1,
            error_code="private-synthetic-detail",
        )
        worker.error_occurred.emit(operation_id, result)
    elif failure_kind == "save":
        result = LifeRecordWorkerResult(
            operation_id=operation_id,
            output=_replacement_output(latest),
            status=ResponseStatus.COMPLETE,
            token_usage=OneShotTokenUsage(1, 1, 2),
            attempt_count=1,
        )
        monkeypatch.setattr(
            "src.ai.life_record_manager.app_paths.save_json_data",
            lambda *_args, **_kwargs: (
                _ for _ in ()
            ).throw(OSError("private-save-detail")),
        )
        worker.result_ready.emit(operation_id, result)
    else:
        worker.requestInterruption()
    worker.finished.emit()

    assert manager.latest() == latest
    assert (tmp_path / "life_records.json").read_bytes() == original_bytes
    assert bridge.llm_client.life_record_manager.latest() == latest
    assert bridge.life_record_state.phase == "idle"
    assert bridge.drains == 1
    if failure_kind == "cancel":
        assert ("notice", "cancelled") in bridge.events
    else:
        assert ("notice", "save_failed" if failure_kind == "save" else "generation_failed") in bridge.events
    assert "private" not in repr(bridge.events)


def test_stale_duplicate_signals_and_shutdown_have_no_side_effects(monkeypatch, tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    _previous, latest = _seed(manager)
    bridge = _Bridge(manager)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge.regenerate_latest_life_record(latest.id)
    worker = _Worker.instances[-1]
    operation_id = bridge.life_record_state.operation_id
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_replacement_output(latest),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )
    bridge.life_record_state.begin_shutdown()

    worker.result_ready.emit(operation_id, result)
    worker.error_occurred.emit(operation_id, result)
    worker.finished.emit()

    assert manager.latest() == latest
    assert bridge.life_record_state.phase == "shutting_down"
    assert bridge.life_record_state.worker is None
    assert bridge.drains == 0
    assert [event for event in bridge.events if event[0] in {"items", "notice"}] == []
