"""게이트웨이 수명과 독립적인 현재 대화 원장의 중복 방지를 확인한다."""

from dataclasses import FrozenInstanceError

import pytest

from tests.companion_helpers import sample_id


KEY = (1, sample_id(1), sample_id(2), sample_id(3))


def test_gateway_recreation_does_not_reexecute_reserved_request():
    from src.core.companion.requests import RequestLedger

    ledger = RequestLedger()
    first = ledger.reserve(KEY, "body-hash")
    second = ledger.reserve(KEY, "body-hash")
    assert first.is_new is True
    assert second.is_new is False
    assert second.state == "reserved"


def test_same_id_with_other_body_conflicts_without_mutation():
    from src.core.companion.requests import RequestLedger, RequestStateError

    ledger = RequestLedger()
    ledger.reserve(KEY, "body-a")
    with pytest.raises(RequestStateError, match="request_conflict"):
        ledger.reserve(KEY, "body-b")
    assert ledger.lookup(KEY).body_hash == "body-a"


def test_accepted_and_finished_status_is_returned_without_new_reservation():
    from src.core.companion.requests import RequestLedger

    ledger = RequestLedger()
    ledger.reserve(KEY, "body")
    accepted = ledger.mark_accepted(KEY, sample_id(4))
    assert accepted.state == "accepted"
    assert accepted.message_id == sample_id(4)
    ledger.finish(KEY, succeeded=True)
    result = ledger.reserve(KEY, "body")
    assert result.state == "completed" and not result.is_new
    assert result.message_id == sample_id(4)


def test_preparation_can_fail_before_a_public_message_exists():
    from src.core.companion.requests import RequestLedger

    ledger = RequestLedger()
    ledger.reserve(KEY, "body")
    result = ledger.finish(KEY, succeeded=False, code="preparation_failed")
    assert result.state == "failed" and result.message_id is None
    assert ledger.reserve(KEY, "body").code == "preparation_failed"


def test_late_completion_cannot_rewrite_final_state():
    from src.core.companion.requests import RequestLedger, RequestStateError

    ledger = RequestLedger()
    ledger.reserve(KEY, "body")
    ledger.mark_accepted(KEY, sample_id(4))
    result = ledger.finish(KEY, succeeded=True)
    assert ledger.finish(KEY, succeeded=True) == result
    with pytest.raises(RequestStateError, match="invalid_transition"):
        ledger.finish(KEY, succeeded=False, code="late_failure")
    with pytest.raises(RequestStateError, match="invalid_transition"):
        ledger.mark_accepted(KEY, sample_id(5))


def test_gate_rejection_discards_only_a_reservation():
    from src.core.companion.requests import RequestLedger, RequestStateError

    ledger = RequestLedger()
    ledger.reserve(KEY, "body")
    ledger.discard_reservation(KEY)
    assert ledger.lookup(KEY) is None
    ledger.reserve(KEY, "body")
    ledger.mark_accepted(KEY, sample_id(4))
    with pytest.raises(RequestStateError, match="invalid_transition"):
        ledger.discard_reservation(KEY)


def test_other_conversation_and_registration_are_independent():
    from src.core.companion.requests import RequestLedger

    ledger = RequestLedger()
    ledger.reserve(KEY, "body")
    assert ledger.reserve((2, *KEY[1:]), "body").is_new
    assert ledger.reserve((1, sample_id(1), sample_id(5), sample_id(3)), "body").is_new
    ledger.reset()
    assert ledger.lookup(KEY) is None


def test_request_ref_and_records_are_immutable():
    from src.core.companion.requests import RequestLedger, RequestRef

    ref = RequestRef(
        registration_generation=1,
        server_epoch=KEY[1],
        conversation_id=KEY[2],
        request_id=KEY[3],
        source="mobile",
    )
    assert ref.key == KEY
    with pytest.raises(FrozenInstanceError):
        ref.request_id = sample_id(4)
    record = RequestLedger().reserve(KEY, "body")
    with pytest.raises(FrozenInstanceError):
        record.state = "completed"
