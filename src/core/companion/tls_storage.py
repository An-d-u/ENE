"""OS 보호 보관과 등록 지문을 결합한다. 초기화는 로컬 소유자만 호출한다."""

from dataclasses import replace
import json
import ssl

from cryptography.hazmat.primitives import serialization

from .private_files import PrivateDirectory
from .protocol import MAX_SAFE_INTEGER
from .tls_identity import TlsError, TlsIdentity, utc_now


class TlsIdentityStore:
    def __init__(self, registration_store, *, directory=None, clock=utc_now):
        self._registration = registration_store
        self._clock = clock
        self.directory = PrivateDirectory(
            directory
            if directory is not None
            else registration_store.path.parent / "companion_tls"
        )
        self._lease = None
        self._identity = None

    def __enter__(self):
        if self._lease is not None:
            raise TlsError("tls_storage_in_use")
        lease = self.directory.lease()
        lease.__enter__()
        self._lease = lease
        try:
            self.directory.cleanup_temporary()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        lease, self._lease = self._lease, None
        self._identity = None
        if lease is not None:
            lease.__exit__(None, None, None)

    def _require_open(self):
        if self._lease is None:
            raise TlsError("tls_storage_unavailable")

    def _write(self, identity):
        raw = json.dumps(
            identity.to_record(), ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        if len(raw) > 16384:
            raise TlsError("tls_identity_invalid")
        self.directory.atomic_write("identity.json", raw)

    def load_or_create(self):
        self._require_open()
        record = self._registration.load_or_create()
        raw = self.directory.read("identity.json")
        # 빈 지문과 증가한 세대는 초기화 중단 표식이다. 남아 있는 옛 CA를 재채택하지 않는다.
        first_run = (
            record.registration_generation == 0
            and record.token_hash is None
            and record.ca_sha256 is None
        )
        if record.ca_sha256 is None and not first_run:
            raise TlsError("tls_repair_required")
        if raw is None:
            if not first_run:
                raise TlsError("tls_repair_required")
            identity = TlsIdentity.create(record.server_id, self._clock())
            self._write(identity)
        else:
            try:
                identity = TlsIdentity.from_record(
                    json.loads(raw.decode("utf-8")), self._clock()
                )
            except (UnicodeError, ValueError, RecursionError) as error:
                if isinstance(error, TlsError):
                    raise
                raise TlsError() from None
        if identity.server_id != record.server_id or record.ca_sha256 not in (
            None,
            identity.ca_sha256,
        ):
            raise TlsError("tls_repair_required")
        if first_run:
            self._registration.save(replace(record, ca_sha256=identity.ca_sha256))
        self._identity = identity
        return identity

    def save(self, identity):
        self._require_open()
        record = self._registration.load_or_create()
        if (
            self._identity is None
            or identity.server_id != record.server_id
            or identity.ca_sha256 != record.ca_sha256
            or identity.ca_sha256 != self._identity.ca_sha256
        ):
            raise TlsError("tls_repair_required")
        self._write(identity)
        self._identity = identity

    def server_context(self, identity):
        self._require_open()
        identity.validate_connection(self._clock())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        pem = (
            identity.leaf_key_pem
            + identity.leaf.public_bytes(serialization.Encoding.PEM)
            + identity.ca.public_bytes(serialization.Encoding.PEM)
        )
        try:
            with self.directory.temporary_file(pem) as path:
                context.load_cert_chain(path)
        except ssl.SSLError:
            raise TlsError("tls_identity_invalid") from None
        return context

    def reset(self):
        self._require_open()
        record = self._registration.load_or_create()
        if record.registration_generation >= MAX_SAFE_INTEGER:
            raise TlsError("tls_repair_required")
        revoked = replace(
            record,
            registration_generation=record.registration_generation + 1,
            device_id=None,
            token_hash=None,
            ca_sha256=None,
        )
        self._registration.save(revoked)
        self._identity = None
        identity = TlsIdentity.create(record.server_id, self._clock())
        self._write(identity)
        self._registration.save(replace(revoked, ca_sha256=identity.ca_sha256))
        self._identity = identity
        return identity
