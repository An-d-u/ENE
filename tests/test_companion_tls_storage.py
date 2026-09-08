"""서버 신원과 등록 결합은 개인 데이터가 없는 임시 보관에서만 시험한다."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import ssl

import pytest

from src.core.companion.storage import RegistrationStore
from tests.companion_helpers import sample_id


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_identity_and_registration_fingerprint_survive_restart(tmp_path):
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        assert registration.load_or_create().ca_sha256 == first.ca_sha256
        assert first.ca_certificate not in repr(store)
        context = store.server_context(first)
        assert context.protocol == ssl.PROTOCOL_TLS_SERVER
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert not list(store.directory.path.glob("tls-load-*.pem"))
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        restored = store.load_or_create()
        assert restored.ca_sha256 == first.ca_sha256
        assert restored.leaf_key_pem == first.leaf_key_pem


def test_missing_key_with_existing_registration_requires_local_repair(tmp_path):
    from src.core.companion.tls_identity import TlsError
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        (store.directory.path / "identity.json").unlink()
        with pytest.raises(TlsError, match="tls_repair_required"):
            store.load_or_create()
        assert registration.load_or_create().ca_sha256 == first.ca_sha256
        assert not (store.directory.path / "identity.json").exists()


def test_old_cleartext_registration_is_not_adopted_under_a_new_ca(tmp_path):
    from src.core.companion.tls_identity import TlsError
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    old = replace(
        registration.load_or_create(),
        registration_generation=1,
        device_id=sample_id(2),
        token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
    )
    registration.save(old)
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        with pytest.raises(TlsError, match="tls_repair_required"):
            store.load_or_create()
        assert registration.load_or_create() == old


def test_reset_revokes_registration_before_installing_a_new_identity(tmp_path):
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        old = replace(
            registration.load_or_create(),
            registration_generation=1,
            device_id=sample_id(2),
            token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        )
        registration.save(old)
        second = store.reset()
        current = registration.load_or_create()
        assert current.registration_generation == 2
        assert current.token_hash is None and current.device_id is None
        assert current.ca_sha256 == second.ca_sha256 != first.ca_sha256


def test_reset_failure_between_revocation_and_identity_write_stays_blocked(
    tmp_path, monkeypatch
):
    from src.core.companion.private_files import PrivateFileError
    from src.core.companion.tls_identity import TlsError
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        store.load_or_create()
        old = registration.load_or_create()

        def fail_write(*_args, **_kwargs):
            raise PrivateFileError("tls_write_failed")

        monkeypatch.setattr(store.directory, "atomic_write", fail_write)
        with pytest.raises(PrivateFileError):
            store.reset()
        revoked = registration.load_or_create()
        assert revoked.registration_generation == old.registration_generation + 1
        assert revoked.ca_sha256 is None and revoked.token_hash is None
    with TlsIdentityStore(registration, clock=lambda: NOW) as restarted:
        with pytest.raises(TlsError, match="tls_repair_required"):
            restarted.load_or_create()


@pytest.mark.parametrize(
    "mutation",
    ["broken", "different-fingerprint", "different-server", "mixed-private-key"],
)
def test_malformed_or_mismatched_storage_is_not_silently_recreated(tmp_path, mutation):
    from src.core.companion.tls_identity import TlsError, TlsIdentity
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        if mutation == "different-fingerprint":
            registration.save(
                replace(registration.load_or_create(), ca_sha256="0" * 64)
            )
        elif mutation == "different-server":
            registration.save(
                replace(registration.load_or_create(), server_id=sample_id(44))
            )
        else:
            payload = first.to_record()
            payload["ca_key_pem"] = TlsIdentity.create(sample_id(99), NOW).to_record()[
                "ca_key_pem"
            ]
            raw = b"{" if mutation == "broken" else json.dumps(payload).encode()
            store.directory.atomic_write("identity.json", raw)
        before = store.directory.read("identity.json")
        with pytest.raises(TlsError):
            store.load_or_create()
        assert store.directory.read("identity.json") == before


def test_same_ca_leaf_renewal_is_persisted_without_changing_registration(tmp_path):
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        record = registration.load_or_create()
        renewed = first.renew(NOW + timedelta(days=61))
        store.save(renewed)
        assert registration.load_or_create() == record
    with TlsIdentityStore(
        registration, clock=lambda: NOW + timedelta(days=61)
    ) as store:
        assert store.load_or_create().leaf_certificate == renewed.leaf_certificate


@pytest.mark.parametrize("stage", ["revoke", "bind", "uncertain-bind"])
def test_reset_registration_write_failures_never_restore_old_token(
    tmp_path, monkeypatch, stage
):
    from src.core.companion.storage import StorageError
    from src.core.companion.tls_identity import TlsError
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=lambda: NOW) as store:
        first = store.load_or_create()
        old = replace(
            registration.load_or_create(),
            registration_generation=1,
            device_id=sample_id(2),
            token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        )
        registration.save(old)
        saved = registration.save

        def fail(record):
            if stage == "revoke" or record.ca_sha256 is not None:
                if stage == "uncertain-bind":
                    saved(record)
                raise StorageError(
                    "storage_uncertain"
                    if stage == "uncertain-bind"
                    else "storage_write_failed"
                )
            saved(record)

        monkeypatch.setattr(registration, "save", fail)
        with pytest.raises(StorageError):
            store.reset()
        current = registration.load_or_create()
        if stage == "revoke":
            assert current == old
            assert (
                store.directory.read("identity.json")
                == json.dumps(first.to_record(), separators=(",", ":")).encode()
            )
        else:
            assert current.token_hash is None and current.registration_generation == 2
        monkeypatch.setattr(registration, "save", saved)
    with TlsIdentityStore(registration, clock=lambda: NOW) as restarted:
        if stage == "bind":
            with pytest.raises(TlsError, match="tls_repair_required"):
                restarted.load_or_create()
        else:
            identity = restarted.load_or_create()
            assert identity.ca_sha256 == current.ca_sha256


def test_closed_store_cannot_write_or_load_keys(tmp_path):
    from src.core.companion.tls_identity import TlsError
    from src.core.companion.tls_storage import TlsIdentityStore

    with TlsIdentityStore(
        RegistrationStore(tmp_path / "registration.json"), clock=lambda: NOW
    ) as store:
        first = store.load_or_create()
    for action in (
        store.load_or_create,
        store.reset,
        lambda: store.save(first),
        lambda: store.server_context(first),
    ):
        with pytest.raises(TlsError, match="tls_storage_unavailable"):
            action()
