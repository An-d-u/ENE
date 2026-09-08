"""서버 루프에서 직렬 실행하는 일회용 QR·등록 상태 기계."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import time
from uuid import uuid4

from .network import Endpoint, normalize_endpoint, select_endpoints
from .protocol import MAX_SAFE_INTEGER, ProtocolError, text_value
from .storage import RegistrationRecord, RegistrationStore, StorageError


class PairingError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PairingTicket:
    server_id: str
    pairing_id: str
    secret: str = field(repr=False)
    expires_at: str
    expires_monotonic: float = field(repr=False)
    addresses: tuple[Endpoint, ...]

    def to_json(self):
        raw = json.dumps(
            {
                "protocol_version": 1,
                "server_id": self.server_id,
                "pairing_id": self.pairing_id,
                "secret": self.secret,
                "expires_at": self.expires_at,
                "addresses": [endpoint.to_dict() for endpoint in self.addresses],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(raw.encode("utf-8")) > 2048:
            raise PairingError("qr_too_large")
        return raw


@dataclass(frozen=True)
class PendingPairing:
    pairing_id: str
    connection_id: str
    device_name: str = field(repr=False)


@dataclass(frozen=True)
class PairingGrant:
    connection_id: str
    pairing_id: str
    registration: RegistrationRecord
    token: str = field(repr=False)

    def to_wire(self):
        registration = self.registration
        return {
            "type": "pair_approved",
            "protocol_version": 1,
            "pairing_id": self.pairing_id,
            "server_id": registration.server_id,
            "device_id": registration.device_id,
            "registration_generation": registration.registration_generation,
            "token": self.token,
        }


class PairingService:
    def __init__(
        self,
        store: RegistrationStore,
        *,
        monotonic=time.monotonic,
        utcnow=None,
        id_factory=None,
        token_factory=None,
    ):
        self.store = store
        self._monotonic = monotonic
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._registration = store.load_or_create()
        self._trusted = True
        self._qr: PairingTicket | None = None
        self._pending: PendingPairing | None = None

    @property
    def registration(self):
        return self._registration

    @property
    def pending(self):
        return self._pending

    @property
    def qr(self):
        self.expire()
        return self._qr

    def _ensure_trusted(self):
        if not self._trusted:
            raise PairingError("storage_uncertain")

    def invalidate(self):
        """QR 수명만 끝낸다. 저장된 등록과 이미 수락한 AI 작업은 변경하지 않는다."""
        self._qr = None
        self._pending = None

    def expire(self):
        if self._qr is not None and self._monotonic() >= self._qr.expires_monotonic:
            pending = self._pending
            self.invalidate()
            return pending
        return None

    def issue_qr(self, addresses):
        self._ensure_trusted()
        normalized = tuple(
            dict.fromkeys(
                normalize_endpoint(item.host, item.port) for item in addresses
            )
        )
        if not normalized or len(normalized) > 8:
            raise PairingError("no_address")
        if any(not select_endpoints([item.host], item.port) for item in normalized):
            raise PairingError("invalid_endpoint")
        expiry = self._utcnow().astimezone(timezone.utc) + timedelta(seconds=120)
        ticket = PairingTicket(
            self._registration.server_id,
            self._id_factory(),
            self._token_factory(),
            expiry.isoformat().replace("+00:00", "Z"),
            self._monotonic() + 120,
            normalized,
        )
        ticket.to_json()
        self.invalidate()
        self._qr = ticket
        return ticket

    def _ticket_for(self, pairing_id):
        self._ensure_trusted()
        self.expire()
        if self._qr is None:
            raise PairingError("pairing_expired")
        if self._qr.pairing_id != pairing_id:
            raise PairingError("invalid_pairing")
        return self._qr

    def request(self, pairing_id, secret, connection_id, device_name):
        ticket = self._ticket_for(pairing_id)
        if (
            not isinstance(secret, str)
            or not secret.isascii()
            or not hmac.compare_digest(ticket.secret, secret)
        ):
            raise PairingError("invalid_pairing")
        try:
            text_value(device_name, nonblank=True)
            if len(device_name) > 80:
                raise ProtocolError()
        except ProtocolError:
            raise PairingError("invalid_pairing") from None
        if self._pending is not None:
            if self._pending.connection_id == connection_id:
                return self._pending
            raise PairingError("pairing_in_use")
        self._pending = PendingPairing(pairing_id, connection_id, device_name)
        return self._pending

    def _save_registration(self, registration):
        try:
            self.store.save(registration)
        except StorageError as error:
            self.invalidate()
            if error.code == "storage_uncertain":
                self._trusted = False
            raise
        self._registration = registration
        self.invalidate()

    def _next_generation(self):
        if self._registration.registration_generation >= MAX_SAFE_INTEGER:
            raise PairingError("generation_exhausted")
        return self._registration.registration_generation + 1

    def approve(self, pairing_id, connection_id):
        """호출자가 Qt 구등록 접수를 먼저 차단하고 새 세대 확인 후에만 grant를 전송한다."""
        self._ticket_for(pairing_id)
        if self._pending is None or self._pending.connection_id != connection_id:
            raise PairingError("invalid_pairing")
        token = self._token_factory()
        registration = RegistrationRecord(
            self._registration.server_id,
            self._next_generation(),
            self._id_factory(),
            hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        self._save_registration(registration)
        return PairingGrant(connection_id, pairing_id, registration, token)

    def reject(self, pairing_id):
        self._ticket_for(pairing_id)
        pending = self._pending
        self.invalidate()
        return pending

    def connection_closed(self, connection_id):
        if self._pending is not None and self._pending.connection_id == connection_id:
            self.invalidate()

    def authorize(self, token):
        self._ensure_trusted()
        digest = self._registration.token_hash
        if (
            digest is None
            or not isinstance(token, str)
            or len(token) != 43
            or not token.isascii()
        ):
            raise PairingError("unauthorized")
        candidate = hashlib.sha256(token.encode("ascii")).hexdigest()
        if not hmac.compare_digest(digest, candidate):
            raise PairingError("unauthorized")
        return self._registration

    def revoke(self):
        """로컬 PC 승인 경로에서만 호출하며 Qt 접수 차단 장벽이 선행해야 한다."""
        self._ensure_trusted()
        registration = RegistrationRecord(
            self._registration.server_id, self._next_generation()
        )
        self._save_registration(registration)
        return registration
