import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.ai.life_record_manager import (
    LifeRecordManager,
    LifeRecordStoreError,
    to_public_dict,
)
from src.ai.life_record_types import (
    LifeRecordOutput,
    create_life_record,
    life_record_store_to_dict,
    stable_life_record_id,
)
from src.core import app_paths


SEOUL = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def _mood() -> dict[str, object]:
    return {
        "label": "차분함",
        "valence": 0.2,
        "energy": 0.4,
        "bond": 0.5,
        "stress": 0.1,
        "short_term_mood": "안정적",
    }


def _record(
    start: datetime,
    end: datetime,
    *,
    created_at: datetime | None = None,
    source: str = "graceful_exit",
):
    created = created_at or end
    place = "가상 도서관"
    return create_life_record(
        id=stable_life_record_id(start, end),
        inactive_started_at=start,
        returned_at=end,
        created_at=created,
        updated_at=created,
        revision=1,
        timezone=getattr(start.tzinfo, "key", "UTC"),
        inactive_start_source=source,
        mood_snapshot=_mood(),
        entries=[
            {
                "started_at": start,
                "ended_at": end,
                "place": place,
                "activity": "합성 자료 정리",
            }
        ],
        ending_state={"place": place, "summary": "정리를 마침"},
    )


def _generated(record, *, activity: str = "새 합성 활동") -> LifeRecordOutput:
    entry_type = type(record.entries[0])
    ending_type = __import__(
        "src.ai.life_record_types", fromlist=["LifeRecordEndingState"]
    ).LifeRecordEndingState
    return LifeRecordOutput(
        entries=(
            entry_type(
                started_at=record.inactive_started_at,
                ended_at=record.returned_at,
                place="가상 공원",
                activity=activity,
            ),
        ),
        ending_state=ending_type(place="가상 공원", summary="산책을 마침"),
    )


def _force_store_bridge(monkeypatch, runtime_root: Path, visible_root: Path) -> None:
    monkeypatch.setattr(app_paths, "is_windows_store_python_runtime", lambda: True)
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name="ENE": runtime_root)
    monkeypatch.setattr(
        app_paths, "get_visible_user_data_dir", lambda app_name="ENE": visible_root
    )
    monkeypatch.delenv(app_paths.USER_DATA_DIR_ENV, raising=False)


def test_new_manager_starts_with_version_one_empty_store(tmp_path):
    path = tmp_path / "life_records.json"

    manager = LifeRecordManager(path)

    assert manager.records == ()
    assert manager.store_status == "missing"
    record = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )
    assert manager.add(record) is True
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_duplicate_add_is_prevented_and_latest_uses_stable_order(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    earlier = _record(
        datetime(2099, 6, 1, 8, tzinfo=SEOUL),
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
    )
    tied_later_created = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
        created_at=datetime(2099, 6, 1, 10, 2, tzinfo=SEOUL),
    )
    tied_earlier_created = _record(
        datetime(2099, 6, 1, 8, 30, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
        created_at=datetime(2099, 6, 1, 10, 1, tzinfo=SEOUL),
    )

    assert manager.add(earlier) is True
    assert manager.add(tied_earlier_created) is True
    assert manager.add(tied_later_created) is True
    assert manager.add(tied_later_created) is False
    assert manager.latest() == tied_later_created
    assert manager.records == (tied_later_created, tied_earlier_created, earlier)


def test_records_overlap_current_view_timezone_and_preserve_record_timezone(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    crossing = _record(
        datetime(2099, 6, 1, 23, 30, tzinfo=SEOUL),
        datetime(2099, 6, 2, 0, 30, tzinfo=SEOUL),
    )
    manager.add(crossing)

    assert manager.records_overlapping_date(date(2099, 6, 1), "Asia/Seoul") == [crossing]
    assert manager.records_overlapping_date(date(2099, 6, 2), "Asia/Seoul") == [crossing]
    assert manager.records_overlapping_date(date(2099, 6, 2), "UTC") == []
    assert crossing.timezone == "Asia/Seoul"


@pytest.mark.parametrize(
    ("local_date", "inside_start", "inside_end", "boundary_start", "boundary_end"),
    [
        (
            date(2099, 3, 8),
            datetime(2099, 3, 8, 0, tzinfo=NEW_YORK),
            datetime(2099, 3, 9, 0, tzinfo=NEW_YORK),
            datetime(2099, 3, 9, 0, tzinfo=NEW_YORK),
            datetime(2099, 3, 9, 1, tzinfo=NEW_YORK),
        ),
        (
            date(2099, 11, 1),
            datetime(2099, 11, 1, 0, tzinfo=NEW_YORK),
            datetime(2099, 11, 2, 0, tzinfo=NEW_YORK),
            datetime(2099, 11, 2, 0, tzinfo=NEW_YORK),
            datetime(2099, 11, 2, 1, tzinfo=NEW_YORK),
        ),
    ],
)
def test_dst_day_bounds_are_real_next_midnight_and_end_exclusive(
    tmp_path, local_date, inside_start, inside_end, boundary_start, boundary_end
):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    inside = _record(inside_start, inside_end)
    at_next_midnight = _record(boundary_start, boundary_end)
    manager.add(inside)
    manager.add(at_next_midnight)

    assert manager.records_overlapping_date(local_date, "America/New_York") == [inside]


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        json.dumps({"version": 1, "records": [{"id": "invalid"}]}),
    ],
)
def test_corrupt_or_json_valid_invalid_store_is_read_error_and_never_overwritten(
    tmp_path, payload
):
    path = tmp_path / "life_records.json"
    path.write_text(payload, encoding="utf-8")
    original = path.read_bytes()

    manager = LifeRecordManager(path)

    assert manager.store_status == "read_error"
    with pytest.raises(LifeRecordStoreError, match="read_error"):
        manager.add(
            _record(
                datetime(2099, 6, 1, 9, tzinfo=SEOUL),
                datetime(2099, 6, 1, 10, tzinfo=SEOUL),
            )
        )
    assert path.read_bytes() == original


def test_date_query_exposes_store_read_error(tmp_path):
    path = tmp_path / "life_records.json"
    path.write_text("{broken", encoding="utf-8")
    manager = LifeRecordManager(path)

    with pytest.raises(LifeRecordStoreError, match="read_error"):
        manager.records_overlapping_date(date(2099, 6, 1), "Asia/Seoul")


def test_duplicate_id_store_is_read_error_and_preserved(tmp_path):
    path = tmp_path / "life_records.json"
    record = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )
    payload = life_record_store_to_dict([record, record])
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()

    manager = LifeRecordManager(path)

    assert manager.store_status == "read_error"
    with pytest.raises(LifeRecordStoreError, match="read_error"):
        manager.replace_latest(record.id, _generated(record), record.updated_at)
    assert path.read_bytes() == original


def test_store_visible_missing_and_read_error_never_use_stale_runtime(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    path = runtime_root / "life_records.json"
    stale = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(life_record_store_to_dict([stale])), encoding="utf-8")
    _force_store_bridge(monkeypatch, runtime_root, visible_root)
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: None)

    missing = LifeRecordManager(path)

    assert missing.store_status == "missing"
    assert missing.records == ()

    def fail_read(path):
        raise PermissionError("합성 읽기 실패")

    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", fail_read)
    failed = LifeRecordManager(path)
    assert failed.store_status == "read_error"
    assert failed.records == ()


def test_save_failure_keeps_memory_unchanged(tmp_path, monkeypatch):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    first = _record(
        datetime(2099, 6, 1, 8, tzinfo=SEOUL),
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
    )
    second = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )
    manager.add(first)
    monkeypatch.setattr(app_paths, "save_json_data", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("합성 저장 실패")))

    with pytest.raises(OSError, match="합성 저장 실패"):
        manager.add(second)

    assert manager.records == (first,)
    assert manager.latest() == first


def test_visible_commit_failure_keeps_file_and_memory(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    path = runtime_root / "life_records.json"
    _force_store_bridge(monkeypatch, runtime_root, visible_root)
    visible_payload = {"value": json.dumps({"version": 1, "records": []}).encode()}
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: visible_payload["value"])

    def fail_visible(path, payload):
        raise OSError("합성 visible 교체 실패")

    monkeypatch.setattr(app_paths, "_write_file_bytes_via_powershell", fail_visible)
    manager = LifeRecordManager(path)
    record = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )

    with pytest.raises(OSError, match="합성 visible 교체 실패"):
        manager.add(record)
    assert manager.records == ()
    assert json.loads(visible_payload["value"])["records"] == []


def test_visible_success_runtime_cache_failure_survives_current_and_restart(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    path = runtime_root / "life_records.json"
    _force_store_bridge(monkeypatch, runtime_root, visible_root)
    visible_payload = {"value": json.dumps({"version": 1, "records": []}).encode()}
    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", lambda path: visible_payload["value"])
    monkeypatch.setattr(
        app_paths,
        "_write_file_bytes_via_powershell",
        lambda path, payload: visible_payload.__setitem__("value", payload),
    )
    monkeypatch.setattr(
        app_paths,
        "_write_file_bytes_atomic_python",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("합성 cache 실패")),
    )
    manager = LifeRecordManager(path)
    record = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )

    assert manager.add(record) is True
    assert manager.latest() == record
    assert LifeRecordManager(path).latest() == record


def test_replace_latest_preserves_metadata_and_previous_before_excludes_self(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    previous = _record(
        datetime(2099, 6, 1, 8, tzinfo=SEOUL),
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
    )
    latest = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
        source="heartbeat_recovery",
    )
    manager.add(previous)
    manager.add(latest)
    updated_at = datetime(2099, 6, 1, 10, 5, tzinfo=SEOUL)

    replaced = manager.replace_latest(latest.id, _generated(latest), updated_at)

    assert manager.previous_before(latest.id) == previous
    assert manager.previous_before(previous.id) is None
    for field in (
        "id",
        "inactive_started_at",
        "returned_at",
        "created_at",
        "timezone",
        "inactive_start_source",
        "mood_snapshot",
    ):
        assert getattr(replaced, field) == getattr(latest, field)
    assert replaced.updated_at == updated_at
    assert replaced.revision == latest.revision + 1
    assert replaced.entries[0].activity == "새 합성 활동"


def test_replace_latest_rejects_non_latest_id_without_mutation(tmp_path):
    manager = LifeRecordManager(tmp_path / "life_records.json")
    previous = _record(
        datetime(2099, 6, 1, 8, tzinfo=SEOUL),
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
    )
    latest = _record(
        datetime(2099, 6, 1, 9, tzinfo=SEOUL),
        datetime(2099, 6, 1, 10, tzinfo=SEOUL),
    )
    manager.add(previous)
    manager.add(latest)
    before = manager.records

    with pytest.raises(LifeRecordStoreError, match="not_latest"):
        manager.replace_latest(previous.id, _generated(previous), previous.updated_at)

    assert manager.records == before


def test_public_dict_is_detached_and_uses_requested_view_timezone(tmp_path):
    record = _record(
        datetime(2099, 6, 1, 23, tzinfo=SEOUL),
        datetime(2099, 6, 2, 0, tzinfo=SEOUL),
    )

    public = to_public_dict(record, "UTC", "ko")
    public["entries"][0]["activity"] = "외부 변경"
    public["mood_snapshot"]["label"] = "외부 변경"

    assert public["inactive_started_at"].endswith("+00:00")
    assert public["view_timezone"] == "UTC"
    assert public["locale"] == "ko"
    assert public["timezone"] == "Asia/Seoul"
    assert record.entries[0].activity == "합성 자료 정리"
    assert record.mood_snapshot["label"] == "차분함"
