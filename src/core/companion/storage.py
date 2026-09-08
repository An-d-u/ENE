"""PC 식별자와 등록 검증 해시만 원자적으로 보관한다."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from uuid import uuid4

from src.core.app_paths import get_user_file, save_json_data_atomic
from .protocol import ProtocolError, integer_value, uuid_value


class StorageError(OSError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RegistrationRecord:
    server_id: str
    registration_generation: int = 0
    device_id: str | None = None
    token_hash: str | None = field(default=None, repr=False)
    ca_sha256: str | None = field(default=None, repr=False)

    def to_dict(self):
        value = {
            "server_id": self.server_id,
            "registration_generation": self.registration_generation,
            "device_id": self.device_id,
            "token_hash": self.token_hash,
        }
        if self.ca_sha256 is not None:
            value["ca_sha256"] = self.ca_sha256
        return value


def _record(value):
    try:
        required = {
            "server_id",
            "registration_generation",
            "device_id",
            "token_hash",
        }
        if not isinstance(value, dict) or set(value) not in (
            required,
            required | {"ca_sha256"},
        ):
            raise ProtocolError()
        server_id = uuid_value(value["server_id"])
        generation = integer_value(value["registration_generation"])
        device, digest = value["device_id"], value["token_hash"]
        if (device is None) != (digest is None):
            raise ProtocolError()
        if device is not None:
            device = uuid_value(device)
            if (
                generation < 1
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ProtocolError()
        ca_digest = value.get("ca_sha256")
        if ca_digest is not None and (
            not isinstance(ca_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", ca_digest)
        ):
            raise ProtocolError()
        return RegistrationRecord(server_id, generation, device, digest, ca_digest)
    except ProtocolError:
        raise StorageError("storage_invalid") from None


class RegistrationStore:
    def __init__(self, path=None, *, writer=save_json_data_atomic, id_factory=None):
        self.path = (
            Path(path)
            if path is not None
            else get_user_file("companion_registration.json")
        )
        self._writer = writer
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def _read_raw(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(8193)
        except FileNotFoundError:
            return None
        except OSError:
            raise StorageError("storage_unavailable") from None
        if len(raw) > 8192:
            raise StorageError("storage_invalid")
        return raw

    def load_or_create(self):
        raw = self._read_raw()
        if raw is None:
            record = RegistrationRecord(self._id_factory())
            self.save(record)
            return record
        try:
            return _record(json.loads(raw.decode("utf-8-sig")))
        except (UnicodeError, ValueError, RecursionError):
            raise StorageError("storage_invalid") from None

    def save(self, record: RegistrationRecord):
        validated = _record(record.to_dict())
        before = self._read_raw()
        try:
            self._writer(self.path, validated.to_dict())
        except OSError:
            # 교체 후 내구 확인 실패는 이전 파일 보존을 보장할 수 없다.
            try:
                unchanged = self._read_raw() == before
            except StorageError:
                unchanged = False
            code = "storage_write_failed" if unchanged else "storage_uncertain"
            raise StorageError(code) from None
