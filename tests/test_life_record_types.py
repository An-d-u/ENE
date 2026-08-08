import json
from datetime import datetime, timedelta, timezone
from math import inf, nan
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest

from src.ai.life_record_types import (
    LifeRecordValidationError,
    create_life_record,
    life_record_to_dict,
    parse_and_validate_life_record_output,
    parse_life_record_store,
    stable_life_record_id,
)


SEOUL = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")


def _entry(start: datetime, end: datetime, place: str = "가상 도서관") -> dict:
    return {
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "place": place,
        "activity": "합성 자료 정리",
    }


def _output(start: datetime, end: datetime) -> dict:
    return {
        "entries": [_entry(start, end)],
        "ending_state": {"place": "가상 도서관", "summary": "정리를 마침"},
    }


def _parse(payload: dict, start: datetime, end: datetime, zone: str = "Asia/Seoul"):
    return parse_and_validate_life_record_output(
        json.dumps(payload, ensure_ascii=False),
        inactive_started_at=start,
        returned_at=end,
        timezone_name=zone,
    )


def _mood() -> dict:
    return {
        "label": "차분함",
        "valence": 0.2,
        "energy": 0.4,
        "bond": 0.5,
        "stress": 0.1,
        "short_term_mood": "안정적",
    }


def _record_dict(
    start: datetime | None = None,
    end: datetime | None = None,
    *,
    timezone_name: str = "Asia/Seoul",
) -> dict:
    start = start or datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = end or datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    created = datetime(2099, 6, 1, 10, 1, tzinfo=SEOUL)
    return {
        "id": stable_life_record_id(start, end),
        "inactive_started_at": start.isoformat(),
        "returned_at": end.isoformat(),
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "revision": 1,
        "timezone": timezone_name,
        "inactive_start_source": "graceful_exit",
        "mood_snapshot": _mood(),
        "entries": [_entry(start, end)],
        "ending_state": {"place": "가상 도서관", "summary": "정리를 마침"},
    }


def _assert_code(code: str, function, *args, **kwargs) -> None:
    with pytest.raises(LifeRecordValidationError) as error:
        function(*args, **kwargs)
    assert error.value.code == code
    assert str(error.value) == code


def test_model_output_parses_exact_contract_and_canonicalizes_seconds():
    start = datetime(2099, 6, 1, 9, 0, 0, 900000, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, 0, 800000, tzinfo=SEOUL)

    payload = _parse(_output(start, end), start, end)

    assert len(payload.entries) <= 24
    assert payload.entries[0].started_at.microsecond == 0
    assert payload.entries[-1].ended_at.microsecond == 0
    assert payload.ending_state.place == payload.entries[-1].place
    assert payload.ending_state.summary == "정리를 마침"


def test_model_output_rejects_legacy_ending_status_field():
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    value = _output(start, end)
    value["ending_state"] = {"place": "가상 도서관", "status": "정리를 마침"}

    _assert_code("extra_field", _parse, value, start, end)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(extra=True), "extra_field"),
        (lambda value: value.pop("ending_state"), "missing_field"),
        (lambda value: value.update(entries=[]), "invalid_entries"),
        (
            lambda value: value.update(
                entries=value["entries"] * 25,
            ),
            "invalid_entries",
        ),
        (lambda value: value["entries"][0].update(extra=True), "extra_field"),
        (lambda value: value["entries"][0].update(place=" "), "invalid_text"),
        (lambda value: value["ending_state"].update(extra=True), "extra_field"),
        (lambda value: value["ending_state"].update(summary=""), "invalid_text"),
        (lambda value: value["ending_state"].update(place="다른 장소"), "invalid_ending_state"),
    ],
)
def test_model_output_rejects_shape_and_text_violations(mutation, code):
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    value = _output(start, end)
    mutation(value)

    _assert_code(code, _parse, value, start, end)


@pytest.mark.parametrize(
    ("raw", "valid"),
    [
        ('{"entries": [], "ending_state": {}} 설명', False),
        ('설명 {"entries": [], "ending_state": {}}', False),
        ('```json\n{"entries": [], "ending_state": {}}\n```', True),
    ],
)
def test_parser_only_strips_an_exact_json_code_fence(raw, valid):
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    if valid:
        _assert_code("invalid_entries", parse_and_validate_life_record_output, raw,
                     inactive_started_at=start, returned_at=end, timezone_name="Asia/Seoul")
    else:
        _assert_code("invalid_json", parse_and_validate_life_record_output, raw,
                     inactive_started_at=start, returned_at=end, timezone_name="Asia/Seoul")


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        (
            lambda start, end: [
                _entry(start, start + timedelta(minutes=20)),
                _entry(start + timedelta(minutes=21), end),
            ],
            "gap",
        ),
        (
            lambda start, end: [
                _entry(start, start + timedelta(minutes=21)),
                _entry(start + timedelta(minutes=20), end),
            ],
            "overlap",
        ),
        (lambda start, end: [_entry(end, start)], "invalid_range"),
        (lambda start, end: [_entry(start - timedelta(seconds=1), end)], "out_of_range"),
        (lambda start, end: [_entry(start, end - timedelta(seconds=1))], "out_of_range"),
    ],
)
def test_model_output_rejects_invalid_utc_continuity(entries, code):
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    value = _output(start, end)
    value["entries"] = entries(start, end)

    _assert_code(code, _parse, value, start, end)


def test_model_output_rejects_naive_and_wrong_zone_offset():
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    naive = _output(start, end)
    naive["entries"][0]["started_at"] = "2099-06-01T09:00:00"
    _assert_code("invalid_datetime", _parse, naive, start, end)

    wrong = _output(start, end)
    wrong["entries"][0]["started_at"] = "2099-06-01T09:00:00+08:00"
    _assert_code("invalid_timezone_offset", _parse, wrong, start, end)


def test_model_output_canonicalizes_surrounding_text_whitespace():
    start = datetime(2099, 6, 1, 9, 0, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, tzinfo=SEOUL)
    value = _output(start, end)
    value["entries"][0]["place"] = "  가상 도서관  "
    value["entries"][0]["activity"] = "  합성 자료 정리  "
    value["ending_state"]["place"] = " 가상 도서관 "
    value["ending_state"]["summary"] = "  정리를 마침  "

    payload = _parse(value, start, end)

    assert payload.entries[0].place == "가상 도서관"
    assert payload.entries[0].activity == "합성 자료 정리"
    assert payload.ending_state.place == "가상 도서관"
    assert payload.ending_state.summary == "정리를 마침"


def test_new_york_accepts_folds_and_rejects_spring_gap_and_wrong_offset():
    fold0 = datetime(2099, 11, 1, 1, 0, tzinfo=NEW_YORK, fold=0)
    fold1 = datetime(2099, 11, 1, 1, 30, tzinfo=NEW_YORK, fold=1)
    payload = _parse(_output(fold0, fold1), fold0, fold1, "America/New_York")
    assert payload.entries[0].ended_at.astimezone(timezone.utc) > fold0.astimezone(timezone.utc)

    gap_start = datetime(2099, 3, 8, 2, 10, tzinfo=NEW_YORK)
    gap_end = datetime(2099, 3, 8, 3, 20, tzinfo=NEW_YORK)
    _assert_code(
        "invalid_timezone_offset",
        _parse,
        _output(gap_start, gap_end),
        gap_start,
        gap_end,
        "America/New_York",
    )

    start = datetime(2099, 1, 2, 9, 0, tzinfo=NEW_YORK)
    end = datetime(2099, 1, 2, 10, 0, tzinfo=NEW_YORK)
    wrong = _output(start, end)
    wrong["entries"][0]["started_at"] = "2099-01-02T09:00:00-04:00"
    _assert_code("invalid_timezone_offset", _parse, wrong, start, end, "America/New_York")


def test_stable_id_uses_utc_integer_second_instants():
    start = datetime(2099, 6, 1, 9, 0, 0, 987654, tzinfo=SEOUL)
    end = datetime(2099, 6, 1, 10, 0, 0, 123456, tzinfo=SEOUL)

    assert stable_life_record_id(start, end) == stable_life_record_id(
        start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    )
    assert len(stable_life_record_id(start, end)) == 64


def test_factory_and_serialization_produce_immutable_valid_record():
    data = _record_dict()
    record = create_life_record(**data)
    original_label = record.mood_snapshot["label"]
    data["mood_snapshot"]["label"] = "외부 변경"

    assert record.mood_snapshot["label"] == original_label
    assert isinstance(record.mood_snapshot, MappingProxyType)
    with pytest.raises(TypeError):
        record.ending_state["summary"] = "변경"  # type: ignore[index]
    assert life_record_to_dict(record)["id"] == record.id
    assert life_record_to_dict(record)["ending_state"]["summary"] == "정리를 마침"


def test_store_round_trips_exact_envelope_and_records():
    raw = json.dumps({"version": 1, "records": [_record_dict()]}, ensure_ascii=False)

    records = parse_life_record_store(raw)

    assert len(records) == 1
    assert records[0].revision == 1
    assert records[0].entries[0].place == "가상 도서관"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda envelope: envelope.update(extra=True), "extra_field"),
        (lambda envelope: envelope.pop("records"), "missing_field"),
        (lambda envelope: envelope.update(version=True), "invalid_store"),
        (lambda envelope: envelope.update(version=1.0), "invalid_store"),
        (lambda envelope: envelope.update(version=2), "invalid_store"),
        (lambda envelope: envelope.update(records={}), "invalid_store"),
        (lambda envelope: envelope["records"][0].update(extra=True), "extra_field"),
        (lambda envelope: envelope["records"][0].update(id="0" * 64), "invalid_id"),
        (lambda envelope: envelope["records"][0].update(timezone="Invalid/Zone"), "invalid_timezone"),
        (lambda envelope: envelope["records"][0].update(inactive_start_source="manual"), "invalid_source"),
        (lambda envelope: envelope["records"][0].update(inactive_start_source=[]), "invalid_source"),
        (lambda envelope: envelope["records"][0].update(inactive_start_source={}), "invalid_source"),
        (lambda envelope: envelope["records"][0].update(revision=True), "invalid_revision"),
        (lambda envelope: envelope["records"][0].update(revision=0), "invalid_revision"),
        (
            lambda envelope: envelope["records"][0].update(
                ending_state={"place": "가상 도서관", "status": "정리를 마침"}
            ),
            "extra_field",
        ),
        (lambda envelope: envelope["records"][0]["mood_snapshot"].update(extra=1), "extra_field"),
        (lambda envelope: envelope["records"][0]["mood_snapshot"].update(label=""), "invalid_text"),
        (lambda envelope: envelope["records"][0]["mood_snapshot"].update(valence=True), "invalid_mood"),
        (lambda envelope: envelope["records"][0]["mood_snapshot"].update(valence=nan), "invalid_mood"),
        (lambda envelope: envelope["records"][0]["mood_snapshot"].update(stress=inf), "invalid_mood"),
    ],
)
def test_store_rejects_strict_contract_violations(mutate, code):
    envelope = {"version": 1, "records": [_record_dict()]}
    mutate(envelope)

    _assert_code(code, parse_life_record_store, json.dumps(envelope, ensure_ascii=False))


def test_store_rejects_duplicate_ids_and_invalid_chronology():
    record = _record_dict()
    _assert_code(
        "duplicate_id",
        parse_life_record_store,
        json.dumps({"version": 1, "records": [record, record]}, ensure_ascii=False),
    )

    invalid = _record_dict()
    invalid["updated_at"] = "2099-06-01T09:59:00+09:00"
    _assert_code(
        "invalid_range",
        parse_life_record_store,
        json.dumps({"version": 1, "records": [invalid]}, ensure_ascii=False),
    )


def test_store_rejects_non_object_envelope_with_store_error():
    _assert_code("invalid_store", parse_life_record_store, "[]")


def test_store_canonicalizes_surrounding_text_whitespace():
    record = _record_dict()
    record["entries"][0]["place"] = "  가상 도서관  "
    record["entries"][0]["activity"] = " 합성 자료 정리 "
    record["ending_state"]["place"] = " 가상 도서관 "
    record["ending_state"]["summary"] = " 정리를 마침 "
    record["mood_snapshot"]["label"] = " 차분함 "
    record["mood_snapshot"]["short_term_mood"] = " 안정적 "

    parsed = parse_life_record_store(
        json.dumps({"version": 1, "records": [record]}, ensure_ascii=False)
    )[0]

    assert parsed.entries[0].place == "가상 도서관"
    assert parsed.entries[0].activity == "합성 자료 정리"
    assert parsed.ending_state["place"] == "가상 도서관"
    assert parsed.ending_state["summary"] == "정리를 마침"
    assert parsed.mood_snapshot["label"] == "차분함"
    assert parsed.mood_snapshot["short_term_mood"] == "안정적"


def test_store_rejects_fractional_persisted_endpoint_and_new_york_offset_mismatch():
    fractional = _record_dict()
    fractional["created_at"] = "2099-06-01T10:01:00.100000+09:00"
    _assert_code(
        "invalid_datetime",
        parse_life_record_store,
        json.dumps({"version": 1, "records": [fractional]}, ensure_ascii=False),
    )

    start = datetime(2099, 1, 2, 9, 0, tzinfo=NEW_YORK)
    end = datetime(2099, 1, 2, 10, 0, tzinfo=NEW_YORK)
    wrong = _record_dict(start, end, timezone_name="America/New_York")
    wrong["inactive_started_at"] = "2099-01-02T09:00:00-04:00"
    _assert_code(
        "invalid_timezone_offset",
        parse_life_record_store,
        json.dumps({"version": 1, "records": [wrong]}, ensure_ascii=False),
    )
