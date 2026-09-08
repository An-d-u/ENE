"""PC별 CA와 서버 인증서의 생성·검증. 파일·네트워크 부수효과는 없다."""

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, SignatureAlgorithmOID

from .protocol import uuid_value


TRANSPORT_PROFILE = "tls_v1"
MAX_CA_BYTES = 768
RENEW_BEFORE = timedelta(days=30)


class TlsError(ValueError):
    def __init__(self, code="tls_identity_invalid"):
        self.code = code
        super().__init__(code)


def utc_now():
    return datetime.now(timezone.utc)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TlsError("tls_clock_invalid")
    return value.astimezone(timezone.utc)


def tls_hostname(server_id):
    return f"ene-{uuid_value(server_id)}.invalid"


def _name(text):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def _encoded(certificate):
    return base64.b64encode(
        certificate.public_bytes(serialization.Encoding.DER)
    ).decode("ascii")


def _certificate(encoded, max_bytes=MAX_CA_BYTES):
    if not isinstance(encoded, str) or len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise TlsError()
    raw = base64.b64decode(encoded, validate=True)
    if (
        not raw
        or len(raw) > max_bytes
        or base64.b64encode(raw).decode("ascii") != encoded
    ):
        raise TlsError()
    certificate = x509.load_der_x509_certificate(raw)
    if certificate.public_bytes(serialization.Encoding.DER) != raw:
        raise TlsError()
    if certificate.signature_algorithm_oid != SignatureAlgorithmOID.ECDSA_WITH_SHA256:
        raise TlsError()
    public = certificate.public_key()
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(
        public.curve, ec.SECP256R1
    ):
        raise TlsError()
    known_critical = {
        x509.BasicConstraints.oid,
        x509.KeyUsage.oid,
        x509.ExtendedKeyUsage.oid,
        x509.SubjectAlternativeName.oid,
    }
    if any(
        extension.critical and extension.oid not in known_critical
        for extension in certificate.extensions
    ):
        raise TlsError()
    return certificate


def _valid_at(certificate, now):
    now = _utc(now)
    if now < certificate.not_valid_before_utc:
        raise TlsError("tls_clock_invalid")
    if now >= certificate.not_valid_after_utc:
        raise TlsError("tls_expired")


@dataclass(frozen=True)
class TrustAnchor:
    server_id: str = field(repr=False)
    certificate: x509.Certificate = field(repr=False)

    @property
    def hostname(self):
        return tls_hostname(self.server_id)

    @property
    def der(self):
        return self.certificate.public_bytes(serialization.Encoding.DER)

    @property
    def sha256(self):
        return hashlib.sha256(self.der).hexdigest()

    @classmethod
    def parse(cls, encoded, server_id, now):
        try:
            server_id = uuid_value(server_id)
            certificate = _certificate(encoded)
            certificate.verify_directly_issued_by(certificate)
            if certificate.subject != _name(f"ENE CA {server_id}"):
                raise TlsError()
            constraints = certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            usage = certificate.extensions.get_extension_for_class(x509.KeyUsage)
            if (
                not constraints.critical
                or constraints.value != x509.BasicConstraints(True, 0)
                or not usage.value.key_cert_sign
            ):
                raise TlsError()
            _valid_at(certificate, now)
            return cls(server_id, certificate)
        except TlsError:
            raise
        except Exception:
            raise TlsError() from None


def _key_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _load_key(pem, certificate):
    if not isinstance(pem, str) or len(pem) > 4096:
        raise TlsError()
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if (
        not isinstance(key, ec.EllipticCurvePrivateKey)
        or key.public_key().public_numbers()
        != certificate.public_key().public_numbers()
    ):
        raise TlsError()
    return key


def _usage(ca):
    return x509.KeyUsage(
        digital_signature=not ca,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )


def _issue_leaf(server_id, ca, ca_key, now):
    key = ec.generate_private_key(ec.SECP256R1())
    hostname = tls_hostname(server_id)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(hostname))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(False, None), critical=True)
        .add_extension(_usage(False), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return certificate, key


@dataclass(frozen=True)
class TlsIdentity:
    server_id: str = field(repr=False)
    ca: x509.Certificate = field(repr=False)
    leaf: x509.Certificate = field(repr=False)
    _ca_key: ec.EllipticCurvePrivateKey = field(repr=False)
    _leaf_key: ec.EllipticCurvePrivateKey = field(repr=False)

    @property
    def hostname(self):
        return tls_hostname(self.server_id)

    @property
    def ca_certificate(self):
        return _encoded(self.ca)

    @property
    def leaf_certificate(self):
        return _encoded(self.leaf)

    @property
    def leaf_key_pem(self):
        return _key_pem(self._leaf_key)

    @property
    def ca_sha256(self):
        return hashlib.sha256(
            self.ca.public_bytes(serialization.Encoding.DER)
        ).hexdigest()

    @property
    def leaf_not_after(self):
        return self.leaf.not_valid_after_utc

    @property
    def ca_not_after(self):
        return self.ca.not_valid_after_utc

    @classmethod
    def create(cls, server_id, now):
        server_id, now = uuid_value(server_id), _utc(now)
        key = ec.generate_private_key(ec.SECP256R1())
        name = _name(f"ENE CA {server_id}")
        ca = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(True, 0), critical=True)
            .add_extension(_usage(True), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        TrustAnchor.parse(_encoded(ca), server_id, now)
        leaf, leaf_key = _issue_leaf(server_id, ca, key, now)
        return cls(server_id, ca, leaf, key, leaf_key)

    def ca_repair_due(self, now):
        return self.ca_not_after - _utc(now) <= RENEW_BEFORE

    def renewal_due(self, now):
        return (
            not self.ca_repair_due(now)
            and self.leaf_not_after - _utc(now) <= RENEW_BEFORE
        )

    def validate_connection(self, now):
        _valid_at(self.ca, now)
        _valid_at(self.leaf, now)

    def renew(self, now):
        now = _utc(now)
        if self.ca_repair_due(now):
            raise TlsError("tls_repair_required")
        _valid_at(self.ca, now)
        leaf, key = _issue_leaf(self.server_id, self.ca, self._ca_key, now)
        return TlsIdentity(self.server_id, self.ca, leaf, self._ca_key, key)

    def to_record(self):
        return {
            "version": 1,
            "server_id": self.server_id,
            "ca_certificate": self.ca_certificate,
            "leaf_certificate": self.leaf_certificate,
            "ca_key_pem": _key_pem(self._ca_key).decode("ascii"),
            "leaf_key_pem": self.leaf_key_pem.decode("ascii"),
        }

    @classmethod
    def from_record(cls, value, now):
        try:
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "version",
                    "server_id",
                    "ca_certificate",
                    "leaf_certificate",
                    "ca_key_pem",
                    "leaf_key_pem",
                }
                or type(value["version"]) is not int
                or value["version"] != 1
            ):
                raise TlsError()
            anchor = TrustAnchor.parse(value["ca_certificate"], value["server_id"], now)
            leaf = _certificate(value["leaf_certificate"], 2048)
            leaf.verify_directly_issued_by(anchor.certificate)
            if leaf.subject != _name(anchor.hostname):
                raise TlsError()
            if leaf.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value != x509.BasicConstraints(False, None):
                raise TlsError()
            usage = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
            if not usage.digital_signature or usage.key_cert_sign:
                raise TlsError()
            if list(
                leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            ) != [ExtendedKeyUsageOID.SERVER_AUTH]:
                raise TlsError()
            names = leaf.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            if list(names) != [x509.DNSName(anchor.hostname)]:
                raise TlsError()
            if (
                leaf.not_valid_after_utc > anchor.certificate.not_valid_after_utc
                or leaf.not_valid_after_utc - leaf.not_valid_before_utc
                > timedelta(days=90, minutes=5)
            ):
                raise TlsError()
            if _utc(now) < leaf.not_valid_before_utc:
                raise TlsError("tls_clock_invalid")
            return cls(
                anchor.server_id,
                anchor.certificate,
                leaf,
                _load_key(value["ca_key_pem"], anchor.certificate),
                _load_key(value["leaf_key_pem"], leaf),
            )
        except TlsError:
            raise
        except Exception:
            raise TlsError() from None
