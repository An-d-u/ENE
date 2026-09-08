"""등록 파일은 가상 임시 경로에서만 읽고 쓰며 토큰 원문을 저장하지 않는다."""

from dataclasses import replace
import hashlib
import json
import secrets

import pytest

from tests.companion_helpers import id_factory, sample_id


def test_initial_identity_is_persistent_and_unregistered(tmp_path):
    from src.core.companion.storage import RegistrationStore

    path = tmp_path / "companion_registration.json"
    first = RegistrationStore(path, id_factory=id_factory()).load_or_create()
    second = RegistrationStore(path).load_or_create()
    assert first == second
    assert first.registration_generation == 0
    assert first.device_id is None and first.token_hash is None
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_only_hash_and_registration_identity_are_persisted(tmp_path):
    from src.core.companion.storage import RegistrationStore

    token = secrets.token_urlsafe(32)
    store = RegistrationStore(tmp_path / "companion_registration.json")
    initial = store.load_or_create()
    registered = replace(
        initial,
        registration_generation=1,
        device_id=sample_id(3),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    store.save(registered)
    raw = store.path.read_text(encoding="utf-8")
    assert token not in raw
    assert set(json.loads(raw)) == {
        "server_id",
        "registration_generation",
        "device_id",
        "token_hash",
    }
    assert RegistrationStore(store.path).load_or_create() == registered


@pytest.mark.parametrize(
    "raw",
    [b"{", b"\xff", b"x" * 8193, b"{}"],
    ids=["broken-json", "invalid-utf8", "oversize", "missing-fields"],
)
def test_invalid_storage_is_not_silently_overwritten(tmp_path, raw):
    from src.core.companion.storage import RegistrationStore, StorageError

    path = tmp_path / "companion_registration.json"
    path.write_bytes(raw)
    with pytest.raises(StorageError, match="storage_invalid"):
        RegistrationStore(path).load_or_create()
    assert path.read_bytes() == raw


def test_failed_write_preserves_existing_record(tmp_path):
    from src.core.companion.storage import RegistrationStore, StorageError

    path = tmp_path / "companion_registration.json"
    initial = RegistrationStore(path).load_or_create()

    def fail_before_write(_path, _payload):
        raise OSError("가상 디스크 오류")

    store = RegistrationStore(path, writer=fail_before_write)
    with pytest.raises(StorageError, match="storage_write_failed"):
        store.save(replace(initial, registration_generation=1))
    assert RegistrationStore(path).load_or_create() == initial


def test_uncertain_post_replace_error_has_a_distinct_fail_closed_code(tmp_path):
    from src.core.app_paths import save_json_data_atomic
    from src.core.companion.storage import RegistrationStore, StorageError

    path = tmp_path / "companion_registration.json"
    initial = RegistrationStore(path).load_or_create()

    def fail_after_write(path, payload):
        save_json_data_atomic(path, payload)
        raise OSError("가상 내구 확인 오류")

    with pytest.raises(StorageError, match="storage_uncertain"):
        RegistrationStore(path, writer=fail_after_write).save(
            replace(initial, registration_generation=1)
        )


def test_malformed_registration_is_rejected(tmp_path):
    from src.core.companion.storage import RegistrationStore, StorageError

    store = RegistrationStore(tmp_path / "companion_registration.json")
    initial = store.load_or_create()
    for record in [
        replace(initial, registration_generation=True),
        replace(initial, device_id=sample_id(3)),
        replace(initial, token_hash="bad"),
    ]:
        with pytest.raises(StorageError, match="storage_invalid"):
            store.save(record)
    assert store.load_or_create() == initial
