"""QR과 승인 상태 기계를 네트워크·실제 설정 없이 검증한다."""

import json

import pytest

from tests.companion_helpers import FakeClock, id_factory


def service(tmp_path, *, writer=None):
    from src.core.companion.pairing import PairingService
    from src.core.companion.storage import RegistrationStore

    clock = FakeClock()
    options = {"writer": writer} if writer else {}
    store = RegistrationStore(
        tmp_path / "companion_registration.json", id_factory=id_factory(), **options
    )
    return PairingService(
        store,
        monotonic=clock.monotonic,
        utcnow=clock.utcnow,
        id_factory=id_factory(200),
    ), clock


def ticket(service):
    from src.core.companion.network import Endpoint

    return service.issue_qr((Endpoint("192.0.2.10", 8765),))


def register(service, connection="connection-a"):
    qr = ticket(service)
    service.request(qr.pairing_id, qr.secret, connection, "가상 단말")
    return service.approve(qr.pairing_id, connection)


def test_qr_uses_random_secret_and_expires_on_monotonic_clock(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, clock = service(tmp_path)
    qr = ticket(pairing)
    assert len(qr.secret) == 43 and qr.secret not in repr(qr)
    payload = json.loads(qr.to_json())
    assert payload["server_id"] == pairing.registration.server_id
    assert payload["expires_at"] == "2026-01-01T00:02:00Z"
    clock.advance(120)
    with pytest.raises(PairingError, match="pairing_expired"):
        pairing.request(qr.pairing_id, qr.secret, "connection-a", "가상 단말")


def test_wrong_secret_does_not_consume_first_valid_request(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, _ = service(tmp_path)
    qr = ticket(pairing)
    with pytest.raises(PairingError, match="invalid_pairing"):
        pairing.request(qr.pairing_id, "invalid", "wrong", "가상 단말")
    assert (
        pairing.request(qr.pairing_id, qr.secret, "valid", "가상 단말").connection_id
        == "valid"
    )


def test_first_valid_request_binds_qr_and_other_connection_cannot_take_it(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, _ = service(tmp_path)
    qr = ticket(pairing)
    pending = pairing.request(qr.pairing_id, qr.secret, "first", "가상 단말 A")
    with pytest.raises(PairingError, match="pairing_in_use"):
        pairing.request(qr.pairing_id, qr.secret, "second", "가상 단말 B")
    with pytest.raises(PairingError, match="invalid_pairing"):
        pairing.approve(qr.pairing_id, "second")
    assert pairing.pending == pending


@pytest.mark.parametrize("cancel", ["reject", "disconnect", "reissue"])
def test_rejected_closed_and_reissued_qrs_cannot_be_used(tmp_path, cancel):
    from src.core.companion.pairing import PairingError

    pairing, _ = service(tmp_path)
    qr = ticket(pairing)
    pairing.request(qr.pairing_id, qr.secret, "first", "가상 단말")
    if cancel == "reject":
        pairing.reject(qr.pairing_id)
    elif cancel == "disconnect":
        pairing.connection_closed("first")
    else:
        assert ticket(pairing).secret != qr.secret
    with pytest.raises(PairingError):
        pairing.approve(qr.pairing_id, "first")


def test_approval_requires_live_pending_request_and_delivers_once(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, clock = service(tmp_path)
    qr = ticket(pairing)
    with pytest.raises(PairingError):
        pairing.approve(qr.pairing_id, "first")
    pairing.request(qr.pairing_id, qr.secret, "first", "가상 단말")
    clock.advance(119)
    grant = pairing.approve(qr.pairing_id, "first")
    assert pairing.authorize(grant.token) == grant.registration
    assert grant.token not in repr(grant)
    with pytest.raises(PairingError):
        pairing.approve(qr.pairing_id, "first")


def test_expiry_between_request_and_approval_prevents_registration(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, clock = service(tmp_path)
    qr = ticket(pairing)
    pairing.request(qr.pairing_id, qr.secret, "first", "가상 단말")
    clock.advance(120)
    with pytest.raises(PairingError, match="pairing_expired"):
        pairing.approve(qr.pairing_id, "first")
    assert pairing.registration.device_id is None


def test_successful_replacement_and_revoke_invalidate_old_tokens(tmp_path):
    from src.core.companion.pairing import PairingError

    pairing, _ = service(tmp_path)
    first = register(pairing)
    second = register(pairing, "connection-b")
    assert (
        second.registration.registration_generation
        == first.registration.registration_generation + 1
    )
    with pytest.raises(PairingError, match="unauthorized"):
        pairing.authorize(first.token)
    revoked = pairing.revoke()
    assert revoked.device_id is None
    assert (
        revoked.registration_generation
        == second.registration.registration_generation + 1
    )
    with pytest.raises(PairingError, match="unauthorized"):
        pairing.authorize(second.token)


def test_failed_registration_keeps_previous_device(tmp_path, monkeypatch):
    from src.core.companion.storage import StorageError

    pairing, _ = service(tmp_path)
    first = register(pairing)

    def fail(_record):
        raise StorageError("storage_write_failed")

    monkeypatch.setattr(pairing.store, "save", fail)
    with pytest.raises(StorageError, match="storage_write_failed"):
        register(pairing, "connection-b")
    assert pairing.authorize(first.token) == first.registration
    assert pairing.pending is None


def test_uncertain_storage_stops_authentication_instead_of_claiming_old_registration(
    tmp_path, monkeypatch
):
    from src.core.companion.pairing import PairingError
    from src.core.companion.storage import StorageError

    pairing, _ = service(tmp_path)
    first = register(pairing)

    def fail(_record):
        raise StorageError("storage_uncertain")

    monkeypatch.setattr(pairing.store, "save", fail)
    with pytest.raises(StorageError):
        register(pairing, "connection-b")
    with pytest.raises(PairingError, match="storage_uncertain"):
        pairing.authorize(first.token)
    with pytest.raises(PairingError, match="storage_uncertain"):
        ticket(pairing)


def test_late_closed_connection_cannot_cancel_a_new_pairing(tmp_path):
    pairing, _ = service(tmp_path)
    qr = ticket(pairing)
    pairing.request(qr.pairing_id, qr.secret, "new", "가상 단말")
    pairing.connection_closed("old")
    assert pairing.pending.connection_id == "new"


def test_recreated_service_restores_registration_without_plain_token_storage(tmp_path):
    pairing, _ = service(tmp_path)
    grant = register(pairing)
    restored, _ = service(tmp_path)
    assert restored.authorize(grant.token) == grant.registration
    assert restored.qr is None and restored.pending is None
    assert grant.token not in restored.store.path.read_text(encoding="utf-8")


def test_failed_revoke_preserves_the_registered_device(tmp_path, monkeypatch):
    from src.core.companion.storage import StorageError

    pairing, _ = service(tmp_path)
    grant = register(pairing)

    def fail(_record):
        raise StorageError("storage_write_failed")

    monkeypatch.setattr(pairing.store, "save", fail)
    with pytest.raises(StorageError):
        pairing.revoke()
    assert pairing.authorize(grant.token) == grant.registration


def test_approval_output_matches_the_shared_wire_contract(tmp_path):
    from src.core.companion.protocol import decode_message, encode_message

    pairing, _ = service(tmp_path)
    grant = register(pairing)
    assert decode_message(encode_message(grant.to_wire())).to_dict() == grant.to_wire()
